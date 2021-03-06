#coding=utf8

import re
import os
import sys
import json

# input directory
#input_dir = './res_arxiv/logs.xsum.bertscore.top3/'
input_dir = './res_arxiv/logs.xsum.greedy/'

def format_for_auto_eva(srcs, refs, candidates):

    for idx, src in enumerate(srcs):
        ref = refs[idx]
        cand = candidates[idx]
        reference_json["values"].append({"target":[ref]})
        prediction_json["values"].append(cand)
        source_json["values"].append(src)

    ref_fpout = open('./temp/references.json', 'w')
    pred_fpout = open('./temp/predictions.json', 'w')
    source_fpout = open('./temp/sources.json', 'w')

    ref_fpout.write(json.dumps(reference_json))
    pred_fpout.write(json.dumps(prediction_json))
    source_fpout.write(json.dumps(source_json))

    ref_fpout.close()
    pred_fpout.close()
    source_fpout.close()

if __name__ == '__main__':

    src_path = os.path.join(input_dir, 'test.res.src')
    gold_summ_path = os.path.join(input_dir, 'test.res.gold')
    gold_select_path = os.path.join(input_dir, 'test.res.cand_select')
    candid_path = os.path.join(input_dir, 'test.res.candidate')

    srcs = [line.strip().replace(' <q> ', ' ') for line in open(src_path)]
    gold_summs = [line.strip().replace(' <q> ', ' ') for line in open(gold_summ_path)]
    gold_selects = [line.strip().replace(' <q> ', ' ') for line in open(gold_select_path)]
    candidates = [line.strip().replace(' <q> ', ' ') for line in open(candid_path)]
    if gold_mode == 'gold_summ':
        refs = gold_summs
    else:
        refs = gold_selects
    
    if eva_mode == 'auto':
        format_for_auto_eva(srcs, refs, candidates)
    elif eva_mode == 'human':
        format_for_human_eva(srcs, refs, candidates)
    else:
        print ('Can not find eva_mode (\'auto\' or \'human\'). ')
