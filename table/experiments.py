"""
Pytorch implementation of neural symbolic machines
Usage:
    experiments.py --config=<file> [options]

Options:
    -h --help                               show this screen.
    --cuda                                  use GPU
    --config=<file>                         path to config file
    --seed=<int>                            seed [default: 0]
"""

import json
import os
import sys
import time
from typing import List
import ctypes
import numpy as np
import torch
from tensorboardX import SummaryWriter

from nsm.actor import Actor, AllGoodReplayBuffer
from nsm.agent_factory import PGAgent
from nsm.embedding import EmbeddingModel
from nsm.env_factory import QAProgrammingEnv
from nsm.computer_factory import LispInterpreter
from nsm.data_utils import Vocab
import nsm.executor_factory as executor_factory
import table.utils as utils
from nsm.data_utils import load_jsonl
from nsm.evaluator import Evaluator
from nsm.learner import Learner

import multiprocessing
from docopt import docopt


def load_environments(example_files: List[str], table_file: str, vocab_file: str, en_vocab_file: str, embedding_file: str):
    dataset = []
    for fn in example_files:
        dataset += load_jsonl(fn)
    print('{} examples in dataset.'.format(len(dataset)))

    tables = load_jsonl(table_file)
    table_dict = {table['name']: table for table in tables}
    print('{} tables.'.format(len(table_dict)))

    # Load pretrained embeddings.
    embedding_model = EmbeddingModel(vocab_file, embedding_file)

    with open(en_vocab_file, 'r') as f:
        vocab = json.load(f)

    en_vocab = Vocab([])
    en_vocab.load_vocab(vocab)
    print('{} unique tokens in encoder vocab'.format(
        len(en_vocab.vocab)))
    print('{} examples in the dataset'.format(len(dataset)))

    # Create environments.
    environments = create_environments(table_dict, dataset, en_vocab, embedding_model, executor_type='wtq')
    print('{} environments in total'.format(len(environments)))

    return environments


def create_environments(table_dict, dataset, en_vocab, embedding_model, executor_type,
                        max_n_mem=60, max_n_exp=3,
                        pretrained_embedding_size=300):
    all_envs = []

    if executor_type == 'wtq':
        score_fn = utils.wtq_score
        process_answer_fn = lambda x: x
        executor_fn = executor_factory.WikiTableExecutor
    elif executor_type == 'wikisql':
        score_fn = utils.wikisql_score
        process_answer_fn = utils.wikisql_process_answer
        executor_fn = executor_factory.WikiSQLExecutor
    else:
        raise ValueError('Unknown executor {}'.format(executor_type))

    for i, example in enumerate(dataset):
        if i % 100 == 0:
            print('creating environment #{}'.format(i))

        kg_info = table_dict[example['context']]
        executor = executor_fn(kg_info)
        api = executor.get_api()
        type_hierarchy = api['type_hierarchy']
        func_dict = api['func_dict']
        constant_dict = api['constant_dict']

        interpreter = LispInterpreter(
            type_hierarchy=type_hierarchy,
            max_mem=max_n_mem,
            max_n_exp=max_n_exp,
            assisted=True)

        for v in func_dict.values():
            interpreter.add_function(**v)

        interpreter.add_constant(
            value=kg_info['row_ents'],
            type='entity_list',
            name='all_rows')

        de_vocab = interpreter.get_vocab()

        constant_value_embedding_fn = lambda x: utils.get_embedding_for_constant(x, embedding_model,
                                                                                 embedding_size=pretrained_embedding_size)

        env = QAProgrammingEnv(en_vocab, de_vocab,
                               question_annotation=example,
                               answer=process_answer_fn(example['answer']),
                               constants=constant_dict.values(),
                               interpreter=interpreter,
                               constant_value_embedding_fn=constant_value_embedding_fn,
                               score_fn=score_fn,
                               name=example['id'])
        all_envs.append(env)

    return all_envs


def init_interpreter_for_example(example_dict, table_dict):
    executor = executor_factory.WikiTableExecutor(table_dict)
    api = executor.get_api()

    interpreter = LispInterpreter(type_hierarchy=api['type_hierarchy'],
                                  max_mem=60,
                                  max_n_exp=50,
                                  assisted=True)

    for func in api['func_dict'].values():
        interpreter.add_function(**func)

    interpreter.add_constant(value=table_dict['row_ents'],
                             type='entity_list',
                             name='all_rows')

    for constant in api['constant_dict'].values():
        interpreter.add_constant(type=constant['type'],
                                 value=constant['value'])

    for entity in example_dict['entities']:
        interpreter.add_constant(value=entity['value'],
                                 type=entity['type'])

    return interpreter


def run_sample():
    envs = load_environments(["/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/data_split_1/train_split_shard_90-0.jsonl"],
                             "/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/tables.jsonl",
                             vocab_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/raw_input/wikitable_glove_vocab.json",
                             en_vocab_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/en_vocab_min_count_5.json",
                             embedding_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/raw_input/wikitable_glove_embedding_mat.npy")

    config = json.load(open('config.json'))
    agent = PGAgent.build(config)

    # agent.save(config['work_dir'] + '/model.bin')
    # agent2 = PGAgent.load(config['work_dir'] + '/model.bin')

    t1 = time.time()
    agent.beam_search(envs[:5], 32)
    t2 = time.time()
    print(t2 - t1)
    return

    for env in envs:
        agent.decode_examples([env], 10)

    t2 = time.time()
    print(t2 - t1)
    t2 = time.time()
    agent.beam_search(envs, 10)

    t3 = time.time()

    print(t3 - t2)


def run(args):
    config_file = args['--config']
    use_cuda = args['--cuda']

    print(f'load config file [{config_file}]', file=sys.stderr)
    config = json.load(open(config_file))

    work_dir = config['work_dir']
    print(f'work dir [{work_dir}]', file=sys.stderr)

    if not os.path.exists(work_dir):
        print(f'creating work dir [{work_dir}]', file=sys.stderr)
        os.makedirs(work_dir)

    json.dump(config, open(os.path.join(work_dir, 'config.json'), 'w'), indent=2)

    learner_gpu_id = evaluator_gpu_id = -1
    if use_cuda:
        print(f'use cuda', file=sys.stderr)
        learner_gpu_id = 0
        evaluator_gpu_id = 1

    learner = Learner(config, learner_gpu_id)

    evaluator = Evaluator(config, eval_file=config['dev_file'], gpu_id=evaluator_gpu_id)
    learner.register_evaluator(evaluator)

    actor_num = config['actor_num']
    print('initializing %d actors' % actor_num, file=sys.stderr)
    actors = []
    actor_shard_dict = {i: [] for i in range(actor_num)}
    shard_start_id = config['shard_start_id']
    shard_end_id = config['shard_end_id']
    for shard_id in range(shard_start_id, shard_end_id):
        actor_id = shard_id % actor_num
        actor_shard_dict[actor_id].append(shard_id)

    for actor_id in range(actor_num):
        actor = Actor(actor_id, shard_ids=actor_shard_dict[actor_id], config=config)
        learner.register_actor(actor)

        actors.append(actor)

    # actors[0].run()
    print('starting %d actors' % actor_num, file=sys.stderr)
    for actor in actors:
        actor.start()

    print('starting evaluator', file=sys.stderr)
    evaluator.start()

    print('starting learner', file=sys.stderr)
    learner.start()

    print('Learner process {}, evaluator process {}'.format(learner.pid, evaluator.pid), file=sys.stderr)

    for actor in actors:
        actor.join()
    learner.join()
    evaluator.join()


def main():
    args = docopt(__doc__)

    # seed the random number generators
    seed = int(args['--seed'])
    torch.manual_seed(seed)
    if args['--cuda']:
        torch.cuda.manual_seed(seed)
    np.random.seed(seed * 13 // 7)

    run(args)


def sanity_check():
    envs = load_environments(["/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/data_split_1/train_split_shard_90-0.jsonl"],
                             "/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/tables.jsonl",
                             vocab_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/raw_input/wikitable_glove_vocab.json",
                             en_vocab_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/en_vocab_min_count_5.json",
                             embedding_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/raw_input/wikitable_glove_embedding_mat.npy")

    config = json.load(open('config.json'))
    agent = PGAgent.build(config)

    buffer = AllGoodReplayBuffer(agent, envs[0].de_vocab)

    from nsm.actor import load_programs_to_buffer
    load_programs_to_buffer(envs, buffer, config['saved_program_file'])

    trajs1 = buffer._buffer[envs[0].name][:3]
    trajs2 = buffer._buffer[envs[1].name][:3]
    trajs3 = buffer._buffer[envs[2].name][:3]
    trajs4 = buffer._buffer[envs[3].name][:3]
    agent.eval()

    batch_probs = agent(trajs1 + trajs2 + trajs3 + trajs4)

    print(batch_probs)
    for traj in trajs1 + trajs2 + trajs3 + trajs4:
        single_prob = agent.compute_trajectory_prob([traj])
        print(single_prob)
    pass


if __name__ == '__main__':
    # envs = load_environments(["/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/train_examples.jsonl"],
    #                          "/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/tables.jsonl",
    #                          vocab_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/raw_input/wikitable_glove_vocab.json",
    #                          en_vocab_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/processed_input/preprocess_14/en_vocab_min_count_5.json",
    #                          embedding_file="/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable/raw_input/wikitable_glove_embedding_mat.npy")
    #
    # env_dict = {env.name: env for env in envs}
    # env_dict['nt-3035'].interpreter.interactive(assisted=True)

    # examples = load_jsonl("/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/train_examples.jsonl")
    # tables = load_jsonl("/Users/yinpengcheng/Research/SemanticParsing/nsm/data/wikitable_reproduce/processed_input/wtq_preprocess/tables.jsonl")
    # #
    # examples_dict = {e['id']: e for e in examples}
    # tables_dict = {tab['name']: tab for tab in tables}
    # #
    # q_id = 'nt-13522'
    # interpreter = init_interpreter_for_example(examples_dict[q_id], tables_dict[examples_dict[q_id]['context']])
    # interpreter.interactive(assisted=True)

    # run_sample()
    main()
    # sanity_check()
