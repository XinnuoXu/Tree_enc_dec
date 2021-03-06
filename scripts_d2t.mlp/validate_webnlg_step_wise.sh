#!/bin/bash

BASE_DIR=./outputs.webnlg/

#BERT_DATA_PATH=${BASE_DIR}/data.step_wise/
#MODEL_PATH=${BASE_DIR}/models.step_wise/
#LOG_PATH=${BASE_DIR}/logs.step_wise/

BERT_DATA_PATH=${BASE_DIR}/data.single_sentences_step_wise/
MODEL_PATH=${BASE_DIR}/models.step_wise_parallel
LOG_PATH=${BASE_DIR}/logs.step_wise_parallel

mkdir -p ${MODEL_PATH}
mkdir -p ${LOG_PATH}

python train.py \
	-mode validate \
	-input_path ${BERT_DATA_PATH} \
	-model_path ${MODEL_PATH} \
        -tokenizer_path ${BERT_DATA_PATH}/tokenizer.pt \
        -ext_or_abs step \
        -cross_attn_weight_format hard \
        -pred_special_tok '<PRED>' \
        -obj_special_tok '<OBJ>' \
        -predicates_start_from_id 32101 \
        -model_name t5-small \
	-result_path ${LOG_PATH}/validation.res \
	-log_file ${LOG_PATH}/validation.log \
	-max_pos 250 \
	-batch_size 6000 \
	-max_tgt_len 250 \
	-visible_gpus 0 \
