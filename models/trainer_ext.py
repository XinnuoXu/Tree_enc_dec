import os
import json
import numpy as np
import torch

import distributed
from models.reporter_ext import StatisticsExt as Statistics
from models.reporter_ext import ReportMgrExt
from models.logging import logger
from models.loss import ConentSelectionLossCompute
from models.tree_reader import tree_building, headlist_to_string

from tool.analysis_edge import Analysis, attention_evaluation


def _tally_parameters(model):
    n_params = sum([p.nelement() for p in model.parameters()])
    return n_params


def build_trainer(args, device_id, model, optim):
    """
    Simplify `Trainer` creation based on user `opt`s*
    Args:
        opt (:obj:`Namespace`): user options (usually from argument parsing)
        model (:obj:`onmt.models.NMTModel`): the model to train
        fields (dict): dict of fields
        optim (:obj:`onmt.utils.Optimizer`): optimizer used during training
        data_type (str): string describing the type of data
            e.g. "text", "img", "audio"
        model_saver(:obj:`onmt.models.ModelSaverBase`): the utility object
            used to save the model
    """

    grad_accum_count = args.accum_count
    n_gpu = args.world_size
    if device_id >= 0:
        gpu_rank = int(args.gpu_ranks[device_id])
    else:
        gpu_rank = 0
        n_gpu = 0
    print('gpu_rank %d' % gpu_rank)

    report_manager = ReportMgrExt(args.report_every, start_time=-1)
    trainer = Trainer(args, model, optim, grad_accum_count, n_gpu, gpu_rank, report_manager)

    if (model):
        n_params = _tally_parameters(model)
        logger.info('* number of parameters: %d' % n_params)

    return trainer


class Trainer(object):
    """
    Class that controls the training process.

    Args:
            model(:py:class:`onmt.models.model.NMTModel`): translation model
                to train
            train_loss(:obj:`onmt.utils.loss.LossComputeBase`):
               training loss computation
            valid_loss(:obj:`onmt.utils.loss.LossComputeBase`):
               training loss computation
            optim(:obj:`onmt.utils.optimizers.Optimizer`):
               the optimizer responsible for update
            trunc_size(int): length of truncated back propagation through time
            shard_size(int): compute loss in shards of this size for efficiency
            data_type(string): type of the source input: [text|img|audio]
            norm_method(string): normalization methods: [sents|tokens]
            grad_accum_count(int): accumulate gradients this many times.
            report_manager(:obj:`onmt.utils.ReportMgrBase`):
                the object that creates reports, or None
            model_saver(:obj:`onmt.models.ModelSaverBase`): the saver is
                used to save a checkpoint.
                Thus nothing will be saved if this parameter is None
    """

    def __init__(self, args, model, optim,
                 grad_accum_count=1, n_gpu=1, gpu_rank=1,
                 report_manager=None):
        # Basic attributes.
        self.args = args
        self.save_checkpoint_steps = args.save_checkpoint_steps
        self.model = model
        self.optim = optim
        self.grad_accum_count = grad_accum_count
        self.n_gpu = n_gpu
        self.gpu_rank = gpu_rank
        self.report_manager = report_manager
        self.loss = ConentSelectionLossCompute(self.args.sentence_modelling_for_ext)

        self.model_analysis = Analysis()

        assert grad_accum_count > 0
        # Set model in training mode.
        if (model):
            self.model.train()

    def train(self, train_iter_fct, train_steps, valid_iter_fct=None, valid_steps=-1):
        """
        The main training loops.
        by iterating over training data (i.e. `train_iter_fct`)
        and running validation (i.e. iterating over `valid_iter_fct`

        Args:
            train_iter_fct(function): a function that returns the train
                iterator. e.g. something like
                train_iter_fct = lambda: generator(*args, **kwargs)
            valid_iter_fct(function): same as train_iter_fct, for valid data
            train_steps(int):
            valid_steps(int):
            save_checkpoint_steps(int):

        Return:
            None
        """
        logger.info('Start training...')

        # step =  self.optim._step + 1
        step = self.optim._step + 1
        true_batchs = []
        accum = 0
        normalization = 0
        train_iter = train_iter_fct()

        total_stats = Statistics()
        report_stats = Statistics()
        self._start_report_manager(start_time=total_stats.start_time)

        while step <= train_steps:

            reduce_counter = 0
            for i, batch in enumerate(train_iter):
                if self.n_gpu == 0 or (i % self.n_gpu == self.gpu_rank):

                    true_batchs.append(batch)
                    normalization += batch.batch_size
                    accum += 1
                    if accum == self.grad_accum_count:
                        reduce_counter += 1
                        if self.n_gpu > 1:
                            normalization = sum(distributed
                                                .all_gather_list
                                                (normalization))

                        self._gradient_accumulation(
                            true_batchs, normalization, total_stats,
                            report_stats)

                        report_stats = self._maybe_report_training(
                            step, train_steps,
                            [self.optim.learning_rate],
                            report_stats)

                        true_batchs = []
                        accum = 0
                        normalization = 0
                        if (step % self.save_checkpoint_steps == 0 and self.gpu_rank == 0):
                            self._save(step)

                        step += 1
                        if step > train_steps:
                            break
            train_iter = train_iter_fct()

        return total_stats


    def validate(self, valid_iter, step=0):
        """ Validate model.
            valid_iter: validate data iterator
        Returns:
            :obj:`nmt.Statistics`: validation loss statistics
        """
        # Set model in validating mode.
        self.model.eval()
        stats = Statistics()

        with torch.no_grad():
            for batch in valid_iter:
                src = batch.src
                mask_src = batch.mask_src
                tgt = batch.tgt
                mask_tgt = batch.mask_tgt
                clss = batch.clss
                mask_cls = batch.mask_cls
                labels = batch.gt_selection

                sent_scores, mask, _, _ = self.model(src, tgt, mask_src, mask_tgt, clss, mask_cls)

                loss = self.loss._compute_loss_test(labels, sent_scores, mask)
                loss = (loss * mask.float()).sum()

                batch_stats = Statistics(float(loss.cpu().data.numpy()), len(labels))
                stats.update(batch_stats)

            self._report_step(0, step, valid_stats=stats)
            return stats


    def test(self, test_iter, step, cal_lead=False, cal_oracle=False):
        """ Validate model.
            valid_iter: validate data iterator
        Returns:
            :obj:`nmt.Statistics`: validation loss statistics
        """

        # Set model in validating mode.
        def _get_ngrams(n, text):
            ngram_set = set()
            text_length = len(text)
            max_index_ngram_start = text_length - n
            for i in range(max_index_ngram_start + 1):
                ngram_set.add(tuple(text[i:i + n]))
            return ngram_set

        def _block_tri(c, p):
            tri_c = _get_ngrams(3, c.split())
            for s in p:
                tri_s = _get_ngrams(3, s.split())
                if len(tri_c.intersection(tri_s)) > 0:
                    return True
            return False

        if (not cal_lead and not cal_oracle):
            self.model.eval()
        stats = Statistics()

        src_path = '%s.raw_src' % (self.args.result_path)
        can_path = '%s.candidate' % (self.args.result_path)
        gold_path = '%s.gold' % (self.args.result_path)
        gold_select_path = '%s.gold_select' % (self.args.result_path)
        selected_ids_path = '%s.selected_ids' % (self.args.result_path)
        tree_path = '%s.trees' % (self.args.result_path)
        edge_path = '%s.edge' % (self.args.result_path)

        save_src = open(src_path, 'w')
        save_pred = open(can_path, 'w')
        save_gold = open(gold_path, 'w')
        save_gold_select = open(gold_select_path, 'w')
        save_selected_ids = open(selected_ids_path, 'w')
        save_trees = open(tree_path, 'w')
        save_edges = open(edge_path, 'w')

        with torch.no_grad():
            for batch in test_iter:
                src = batch.src
                mask_src = batch.mask_src
                tgt = batch.tgt
                mask_tgt = batch.mask_tgt
                clss = batch.clss
                mask_cls = batch.mask_cls
                labels = batch.gt_selection
                nsent = batch.nsent

                gold = []; pred = []; pred_select = []

                if (cal_lead):
                    selected_ids = [list(range(batch.clss.size(1)))] * batch.batch_size
                elif (cal_oracle):
                    selected_ids = [[j for j in range(batch.clss.size(1)) if labels[i][j] == 1] for i in
                                    range(batch.batch_size)]
                else:
                    sent_scores, mask, aj_matrixes, src_features = self.model(src, tgt, mask_src, mask_tgt, clss, mask_cls)

                    if (self.args.sentence_modelling_for_ext == 'tree'):
                        device = mask.device
                        sent_scores = sent_scores[-1] + mask.float()
                    else:
                        sent_scores = sent_scores+mask.float()

                    sent_scores = sent_scores.cpu().data.numpy()
                    selected_ids = np.argsort(-sent_scores, 1)
                    #selected_ids = np.sort(selected_ids,1)

                sent_nums = torch.sum(mask_cls, 1)
                for i, idx in enumerate(selected_ids):
                    _pred = []; _pred_select = []
                    if (len(batch.src_str[i]) == 0):
                        continue
                    sent_num = sent_nums[i]
                    if self.args.select_topn == 0:
                        select_topn = nsent[i]
                    elif self.args.select_topn > 0 and self.args.select_topn < 1:
                        select_topn = int(sent_num * self.args.select_topn) + 1
                    else:
                        select_topn = int(self.args.select_topn)
                    for j in selected_ids[i][:len(batch.src_str[i])]:
                        if (j >= len(batch.src_str[i])):
                            continue
                        candidate = batch.src_str[i][j].strip()
                        if (self.args.block_trigram):
                            if (not _block_tri(candidate, _pred)):
                                _pred.append(candidate)
                                _pred_select.append(int(j))
                        else:
                            _pred.append(candidate)
                            _pred_select.append(int(j))
                        if (not cal_oracle) and (not self.args.recall_eval) and len(_pred) == select_topn:
                            break

                    _pred = ' <q> '.join(_pred)

                    pred_select.append(_pred_select)
                    pred.append(_pred)
                    gold.append(' <q> '.join(batch.tgt_str[i]))

                selected_ids = [[j for j in range(batch.clss.size(1)) if labels[i][j] == 1] for i in range(batch.batch_size)]

                for i in range(len(gold)):
                    save_gold.write(gold[i].strip()+'\n')
                for i in range(len(pred)):
                    save_pred.write(pred[i].strip()+'\n')
                for i in range(len(batch.src_str)):
                    save_src.write(' '.join(batch.src_str[i]).strip() + '\n')
                for i in range(len(pred_select)):
                    item = {'gold':selected_ids[i], 'pred':pred_select[i]}
                    save_selected_ids.write(json.dumps(item) + '\n')
                for i, idx in enumerate(selected_ids):
                    _gold_selection = [batch.src_str[i][j].strip() for j in selected_ids[i][:len(batch.src_str[i])]]
                    _gold_selection = ' <q> '.join(_gold_selection).strip()
                    save_gold_select.write(_gold_selection + '\n')


                if self.args.do_analysis:

                    # Edge analysis
                    sents_vec = src_features[torch.arange(src_features.size(0)).unsqueeze(1), clss]
                    edge_pred_scores, edge_align_labels = self.model_analysis.edge_ranking_data_processing(sents_vec, batch.alg, mask_cls)
                    for i, edge_pred_score in enumerate(edge_pred_scores):
                        edge_align_label = edge_align_labels[i]
                        n_src_sent = len(batch.src_str[i])
                        edge_structure = {'Pred': edge_pred_score, 'Label': edge_align_label, 'nSent': n_src_sent}
                        save_edges.write(json.dumps(edge_structure) + '\n')

                    # Tree analysis
                    root_selection = torch.zeros(mask.size(), device=mask.device).int()
                    for i, _pred_select in enumerate(pred_select):
                        for sid in _pred_select:
                            root_selection[i][sid] = 1

                    trees = tree_building(root_selection, aj_matrixes, mask, device)
                    for i in range(batch.batch_size):
                        tree, height = headlist_to_string(trees[i])
                        src_list = batch.src_str[i]
                        tree_structure = {'Tree':' '.join(tree), 'Src':['[SENT-'+str(i+1)+'] '+src_list[i] for i in range(len(src_list))], 'Height':height, 'tgt_nsent':nsent[i], 'src_nsent':len(src_list)}
                        save_trees.write(json.dumps(tree_structure)+'\n')

        self._report_step(0, step, valid_stats=stats)
        save_src.close()
        save_gold.close()
        save_pred.close()
        save_gold_select.close()
        save_selected_ids.close()
        save_trees.close()
        save_edges.close()

        return stats

    def _gradient_accumulation(self, true_batchs, normalization, total_stats, report_stats):
        if self.grad_accum_count > 1:
            self.model.zero_grad()

        for batch in true_batchs:
            if self.grad_accum_count == 1:
                self.model.zero_grad()

            src = batch.src
            mask_src = batch.mask_src
            tgt = batch.tgt
            mask_tgt = batch.mask_tgt
            clss = batch.clss
            mask_cls = batch.mask_cls
            labels = batch.gt_selection
            nsent = batch.nsent

            sent_scores, mask, attn, top_vec = self.model(src, tgt, mask_src, mask_tgt, clss, mask_cls)

            # TMP_CODE: training of the edge prediction
            sents_vec = top_vec[torch.arange(top_vec.size(0)).unsqueeze(1), clss]
            edge_pred_scores, edge_align_labels = self.model_analysis.edge_ranking_data_processing(sents_vec, batch.alg, mask_cls)
            edge_pred_scores = [torch.stack(example) for example in edge_pred_scores]
            if len(edge_pred_scores) == 0:
                continue
            sent_scores = [torch.cat(edge_pred_scores).unsqueeze(0)]
            labels = []
            for item in edge_align_labels:
                labels.extend(item)
            labels = torch.tensor(labels, device=src.device).unsqueeze(0)
            mask = torch.ones(labels.size(), device=src.device)
            # TMP_CODE END

            loss = self.loss._compute_loss(labels, sent_scores, mask)
            (loss / loss.numel()).backward()

            # Gradient supervise
            '''
            gradient_monitor = {}
            for name, para in self.model.named_parameters():
                if para.grad is not None:
                    print (torch.mean(para.grad))
            '''

            attn_ma, attn_mi, attn_mean = attention_evaluation(attn[-1], mask_cls)

            batch_stats = Statistics(float(loss.cpu().data.numpy()), normalization, 
                                     attn_ma=attn_ma, 
                                     attn_mi=attn_mi, 
                                     attn_mean=attn_mean)

            total_stats.update(batch_stats)
            report_stats.update(batch_stats)

            # 4. Update the parameters and statistics.
            if self.grad_accum_count == 1:
                # Multi GPU gradient gather
                if self.n_gpu > 1:
                    grads = [p.grad.data for p in self.model.parameters()
                             if p.requires_grad
                             and p.grad is not None]
                    distributed.all_reduce_and_rescale_tensors(
                        grads, float(1))
                self.optim.step()

        # in case of multi step gradient accumulation,
        # update only after accum batches
        if self.grad_accum_count > 1:
            if self.n_gpu > 1:
                grads = [p.grad.data for p in self.model.parameters()
                         if p.requires_grad
                         and p.grad is not None]
                distributed.all_reduce_and_rescale_tensors(
                    grads, float(1))
            self.optim.step()

    def _save(self, step):
        real_model = self.model
        # real_generator = (self.generator.module
        #                   if isinstance(self.generator, torch.nn.DataParallel)
        #                   else self.generator)

        model_state_dict = real_model.state_dict()
        # generator_state_dict = real_generator.state_dict()
        checkpoint = {
            'model': model_state_dict,
            # 'generator': generator_state_dict,
            'opt': self.args,
            'optims': [self.optim],
        }
        checkpoint_path = os.path.join(self.args.model_path, 'model_step_%d.pt' % step)
        logger.info("Saving checkpoint %s" % checkpoint_path)
        # checkpoint_path = '%s_step_%d.pt' % (FLAGS.model_path, step)
        if (not os.path.exists(checkpoint_path)):
            torch.save(checkpoint, checkpoint_path)
            return checkpoint, checkpoint_path

    def _start_report_manager(self, start_time=None):
        """
        Simple function to start report manager (if any)
        """
        if self.report_manager is not None:
            if start_time is None:
                self.report_manager.start()
            else:
                self.report_manager.start_time = start_time

    def _maybe_gather_stats(self, stat):
        """
        Gather statistics in multi-processes cases

        Args:
            stat(:obj:onmt.utils.Statistics): a Statistics object to gather
                or None (it returns None in this case)

        Returns:
            stat: the updated (or unchanged) stat object
        """
        if stat is not None and self.n_gpu > 1:
            return Statistics.all_gather_stats(stat)
        return stat

    def _maybe_report_training(self, step, num_steps, learning_rate,
                               report_stats):
        """
        Simple function to report training stats (if report_manager is set)
        see `onmt.utils.ReportManagerBase.report_training` for doc
        """
        if self.report_manager is not None:
            return self.report_manager.report_training(
                step, num_steps, learning_rate, report_stats,
                multigpu=self.n_gpu > 1)

    def _report_step(self, learning_rate, step, train_stats=None,
                     valid_stats=None):
        """
        Simple function to report stats (if report_manager is set)
        see `onmt.utils.ReportManagerBase.report_step` for doc
        """
        if self.report_manager is not None:
            return self.report_manager.report_step(
                learning_rate, step, train_stats=train_stats,
                valid_stats=valid_stats)

    def _maybe_save(self, step):
        """
        Save the model if a model saver is set
        """
        if self.model_saver is not None:
            self.model_saver.maybe_save(step)
