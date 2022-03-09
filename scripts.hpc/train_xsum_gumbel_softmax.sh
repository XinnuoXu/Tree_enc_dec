#!/bin/bash

BERT_DATA_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs/data/
MODEL_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs/models.gumbel_softmax/
LOG_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs/logs.gumbel_softmax/

mkdir -p ${LOG_PATH}
mkdir -p ${MODEL_PATH}

python train.py  \
	-input_path ${BERT_DATA_PATH} \
	-model_path ${MODEL_PATH} \
	-mode train \
	-ext_or_abs abs \
	-content_planning_model tree \
	-tree_gumbel_softmax_tau 0.5 \
	-log_file ${LOG_PATH}/train.log \
	-train_steps 150000 \
	-save_checkpoint_steps 30000 \
	-warmup_steps 500 \
	-batch_size 3000 \
	-report_every 100 \
	-max_pos 1024 \
	-max_tgt_len 128 \
	-use_interval true \
	-lr 3e-5 \
	-decay_method linear_warmup \
	-accum_count 2 \
	-visible_gpus 0,1,2
