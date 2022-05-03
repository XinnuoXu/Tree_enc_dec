#!/bin/bash

#BASE_DIR=./outputs.webnlg/
BASE_DIR=${SCRATCH_DIR}

BERT_DATA_PATH=${BASE_DIR}/data/
MODEL_PATH=${BASE_DIR}/models.base/
LOG_PATH=${BASE_DIR}/logs.base/

mkdir -p ${MODEL_PATH}
mkdir -p ${LOG_PATH}

python train.py  \
	-input_path ${BERT_DATA_PATH} \
	-model_path ${MODEL_PATH} \
	-model_name ./t5-small \
        -tokenizer_path ${BERT_DATA_PATH}/tokenizer.pt \
	-mode train \
	-ext_or_abs abs \
	-content_planning_model none \
	-log_file ${LOG_PATH}/train.log \
	-train_steps 12000 \
	-save_checkpoint_steps 4000 \
	-warmup_steps 1000 \
	-batch_size 3000 \
	-report_every 100 \
	-max_pos 150 \
	-max_tgt_len 150 \
	-ext_dropout 0.1 \
	-lr 3e-4 \
        -decay_method linear_warmup \
	-accum_count 2 \
	-visible_gpus 0,1,2

