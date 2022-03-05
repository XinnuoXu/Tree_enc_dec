#!/bin/bash

JSON_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs/jsons/
BERT_DATA_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs/data/
LOG_PATH=/home/hpcxu1/Planning/Tree_enc_dec/outputs/logs/

mkdir ${BERT_DATA_PATH}
rm -rf ${BERT_DATA_PATH}/*

python preprocess.py \
	-mode format_for_training \
	-raw_path ${JSON_PATH} \
	-save_path ${BERT_DATA_PATH} \
	-tokenizer facebook/bart-base \
	-n_cpus 1 \
	-log_file ${LOG_PATH}/preprocess.log
