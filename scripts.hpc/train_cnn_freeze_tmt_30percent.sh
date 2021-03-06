#!/bin/bash

BERT_DATA_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.cnn_dm/data/
MODEL_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.cnn_dm/models.freeze_tmt_30percent/
EXT_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.cnn_dm/models.ext/
ABS_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.cnn_dm/models.bartbase/
LOG_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.cnn_dm/logs.freeze_tmt_30percent/

mkdir -p ${MODEL_PATH}
mkdir -p ${LOG_PATH}

python train.py  \
	-input_path ${BERT_DATA_PATH} \
	-model_path ${MODEL_PATH} \
        -load_from_ext ${EXT_PATH}/model_step_60000.pt \
        -load_from_abs ${ABS_PATH}/model_step_320000.pt \
	-mode train \
        -freeze_tmt True \
	-ext_or_abs mix \
	-content_planning_model tree \
	-tree_gumbel_softmax_tau -1 \
        -abs_plus_ext_loss 0 \
        -ext_topn 0.3 \
	-log_file ${LOG_PATH}/train.log \
	-train_steps 320000 \
	-save_checkpoint_steps 80000 \
	-warmup_steps 1000 \
	-batch_size 3000 \
	-report_every 100 \
	-max_pos 1024 \
	-max_tgt_len 250 \
	-lr 3e-5 \
        -decay_method linear_warmup \
	-accum_count 2 \
	-visible_gpus 0,1,2

