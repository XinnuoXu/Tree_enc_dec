#!/bin/bash

BERT_DATA_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.webnlg/data/
MODEL_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.webnlg/models.plan/
LOG_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs.webnlg/logs.plan/

mkdir -p ${LOG_PATH}

python train.py \
	-mode test \
	-input_path ${BERT_DATA_PATH} \
        -tokenizer_path ${BERT_DATA_PATH}/tokenizer.pt \
	-test_from ${MODEL_PATH}/model_step_4000.pt \
	-result_path ${LOG_PATH}/test.res \
	-log_file ${LOG_PATH}/test.log \
        -model_name t5-base \
	-ext_or_abs marginal_projective_tree \
	-content_planning_model tree \
	-inference_mode abs \
        -predicates_start_from_id 32101 \
	-block_trigram true \
	-max_pos 150 \
	-batch_size 6000 \
        -test_min_length 10 \
        -test_max_length 150 \
	-visible_gpus 0 \
