ROOT=$HOME"/THIS_LAPTOP_projects/pytorch_neural_symbolic_machines/"
DATA_DIR=$ROOT"data/wikisql/"
python preprocess.py \
       --raw_input_dir=$DATA_DIR \
       --processed_input_dir=$DATA_DIR"processed_input/"
       # --alsologtostderr
