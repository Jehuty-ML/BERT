# coding=utf-8

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from sklearn.model_selection import train_test_split
import collections
import csv
import os
import json
import bert_modeling as modeling
import optimization
import tokenization
import tensorflow as tf

import math
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.training import moving_averages
from tflearn.layers.conv import global_avg_pool
from tensorflow.contrib.tpu import TPUConfig
from tensorflow.contrib.tpu import RunConfig
from IPython import embed


# Paras for BN
MOVING_AVERAGE_DECAY = 0.9997
BN_DECAY = MOVING_AVERAGE_DECAY
BN_EPSILON = 0.001
CONV_WEIGHT_DECAY = 0.00004
CONV_WEIGHT_STDDEV = 0.1
FC_WEIGHT_DECAY = 0.00004
FC_WEIGHT_STDDEV = 0.01
RESNET_VARIABLES = 'resnet_variables'
UPDATE_OPS_COLLECTION = 'resnet_update_ops'


flags = tf.flags

FLAGS = flags.FLAGS
config = tf.ConfigProto()
#config.gpu_options.allow_growth = True
#config.gpu_options.per_process_gpu_memory_fraction=0.8

flags.DEFINE_string(
    "bert_config_file", "chinese_L-12_H-768_A-12/bert_config.json",
    "The config json file corresponding to the pre-trained BERT model. "
    "This specifies the model architecture.")

flags.DEFINE_string("vocab_file", "chinese_L-12_H-768_A-12/vocab.txt",
                    "The vocabulary file that the BERT model was trained on.")
flags.DEFINE_string(
    "init_checkpoint", "chinese_L-12_H-768_A-12/bert_model.ckpt",
    "Initial checkpoint (usually from a pre-trained BERT model).")

flags.DEFINE_string("task_name", "multi_label", "The name of the task to train.")

flags.DEFINE_string(
    "data_dir", "data/divorce",
    "The input data dir. Should contain the .tsv files (or other data files) "
    "for the task.")

flags.DEFINE_string(
    "output_dir", "output_bert_senet_attention_result/divorce",
    "The output directory where the model checkpoints will be written.")

flags.DEFINE_integer("num_aspects", 20, "Total number of aspect")
flags.DEFINE_integer("num_filters", 128, "Total number of filter")
flags.DEFINE_integer("filter_size", 3, "Total number of filter")

flags.DEFINE_string("train_data_files", "data_small_selected.json,train_selected.json", "train data josn files")

flags.DEFINE_string("test_data_file", "train_selected.json", "test data josn files")

flags.DEFINE_string("tag_flag", "DV", "tag flag")

flags.DEFINE_string("tag_file","tags.txt","tag file")

flags.DEFINE_float("rs_flag",0.5,"result prediction flag")
flags.DEFINE_float("cnn_dropout",1.0,"dropout of CNN")
flags.DEFINE_float("rnn_dropout",0.8,"dropout of rnn")

flags.DEFINE_bool("add_part",False,"result prediction flag")

flags.DEFINE_integer(
    "max_seq_length", 32,
    "The maximum total input sequence length after WordPiece tokenization. "
    "Sequences longer than this will be truncated, and sequences shorter "
    "than this will be padded.")

flags.DEFINE_bool("do_train", True, "Whether to run training.")

flags.DEFINE_bool("do_eval", True, "Whether to run eval on the dev set.")

flags.DEFINE_bool(
    "do_predict", False,
    "Whether to run the model in inference mode on the test set.")

flags.DEFINE_integer("train_batch_size", 2, "Total batch size for training.")
flags.DEFINE_integer("hidden_dim", 128, "Total batch size for training.")
flags.DEFINE_integer("attention_size", 50, "Total batch size for training.")

flags.DEFINE_integer("eval_batch_size", 1, "Total batch size for eval.")

flags.DEFINE_integer("predict_batch_size", 1, "Total batch size for predict.")

flags.DEFINE_float("learning_rate", 5e-5, "The initial learning rate for Adam.")

flags.DEFINE_float("num_train_epochs", 1.0,
                   "Total number of training epochs to perform.")

flags.DEFINE_float(
    "warmup_proportion", 0.1,
    "Proportion of training to perform linear learning rate warmup for. "
    "E.g., 0.1 = 10% of training.")

flags.DEFINE_integer("save_checkpoints_steps", 5,
                     "How often to save the model checkpoint.")

flags.DEFINE_integer("iterations_per_loop", 50,
                     "How many steps to make in each estimator call.")

flags.DEFINE_bool(
    "do_lower_case", True,
    "Whether to lower case the input text. Should be True for uncased "
    "models and False for cased models.")

flags.DEFINE_bool("use_tpu", False, "Whether to use TPU or GPU/CPU.")

tf.flags.DEFINE_string(
    "tpu_name", None,
    "The Cloud TPU to use for training. This should be either the name "
    "used when creating the Cloud TPU, or a grpc://ip.address.of.tpu:8470 "
    "url.")

tf.flags.DEFINE_string(
    "tpu_zone", None,
    "[Optional] GCE zone where the Cloud TPU is located in. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

tf.flags.DEFINE_string(
    "gcp_project", None,
    "[Optional] Project name for the Cloud TPU-enabled project. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

tf.flags.DEFINE_string("master", None, "[Optional] TensorFlow master URL.")

flags.DEFINE_integer(
    "num_tpu_cores",    8,
    "Only used if `use_tpu` is True. Total number of TPU cores to use.")


class RECnn(object):
    '''
     FLAGS.sequence_length,#100
            len(datamanager.relations),#53
            FLAGS.embedding_dim,#50
            5,
            list(map(int, FLAGS.filter_sizes.split(","))),#filter_sizes=3
            FLAGS.num_filters,#128
            FLAGS.l2_reg_lambda)#0.0001'''
    def __init__(
        self, sequence_length, num_classes,
            embedding_size, filter_sizes, num_filters,embedded_chars_expanded,dropout_keep_prob,is_training=False):
            with tf.device('/cpu:0'):
                '''
                 cnn.input_x: #x=[batchsize,句子长，字的长]=[64,100,50]
                cnn.input_y: #直接拿出来就一个向量。one_hot的分类向量[1,0,0,0,0,....]一共53种情况
                cnn.input_p1: #实体1相对于句子中每一个词的位置信息，[0,0,0,0,0,0,0,0,0,31,32,33,34,35,36....,49,0,0,0,0]
                cnn.input_p2: #实体2相对句子句子中每一个词的位置信息，[0,0,0,0,0,0,0,0,0,24,25,26,27,28,29....,42,0,0,0,0]
                '''
                self.dropout_keep_prob = dropout_keep_prob
                self.is_training=is_training

                self.embedded_chars_expanded = embedded_chars_expanded#加上一个维度，类似一个图片。
                #因为要卷积所以加一个维度。(?,100,60,1)

                pooled_outputs = []
                j_index=0
                for i, filter_size in enumerate(filter_sizes):
                    with tf.name_scope("conv-maxpool-%s" % filter_size):
                        #[3,60,1,128]#128个卷积核。60是字的维度，3是宽。1是一个通道。
                        filter_shape = [filter_size, embedding_size, 1, num_filters]#[3,768,1,128]
                        W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")
                        b = tf.Variable(tf.constant(0.1, shape=[num_filters]), name="b")
                        conv = tf.nn.conv2d(
                            self.embedded_chars_expanded, #(?,100,60,1) # NHWC
                            W,  #[3,60,1,128]# filter_height, filter_width, in_channels, out_channels
                            strides=[1, 1, 1, 1],
                            padding="VALID",
                            name="conv")#98*1*128

                        c_ = {'use_bias': True,
                            #condition训练train时true，
                              'is_training': self.is_training}
                              #condition训练时true，
                        conv = self.bn(conv, c_, '{}-bn'.format(i))#取出那个128,要不要加偏执项，就是b,这里的偏执项都是0
                        #一个系数
                        beta2 = tf.Variable(tf.truncated_normal([1], stddev=0.08), name='first-swish')
                        x2 = tf.nn.bias_add(conv, b)#这里的b是一个常量。
                        h = x2 * tf.nn.sigmoid(x2 * beta2)#激活函数一下

                        for j in range(6):
                            j_index +=1
                            h2 = self.Cnnblock(num_filters, h, j_index)#128通道数，上一层卷积的结果，i是第几次。
                            #这里也是一个卷积，#输入是98，1,128——卷积是[3,1,128,128]，padding方式为SAME，表示有最后的128个卷积核，在倒数第二个128通道上卷，宽口大小是3*1
                            #卷完之后是[?,98,1,128]?代表betchsize,128是输出的通道数。
                            h = h2+h

                        pooled = tf.nn.max_pool(
                            h,
                            ksize=[1, sequence_length - filter_size + 1, 1, 1],#sequence_length - filter_size + 1=98
                            strides=[1, 1, 1, 1],
                            padding='VALID',
                            name="pool")
                        pooled_avg = tf.nn.avg_pool(
                            h,
                            ksize=[1, sequence_length - filter_size + 1, 1, 1],
                            strides=[1, 1, 1, 1],
                            padding='VALID',
                            name="pool")
                        ###[3,4,5]三次，所以num_filters*6而不是num_filters*2
                        pooled_outputs.append(pooled)
                        pooled_outputs.append(pooled_avg)

                num_filters_total = num_filters*6#128*2=256
                #在尺寸变[3,4,5]后这个地方要num_filters*2变成num_filters*6。
                self.num_filters_total=num_filters_total

                self.h_pool = tf.concat(pooled_outputs, 3)#拼接
                #[?,256]
                #(32, 1, 1, 768)在reshape后[32,768]
                self.h_pool_flat = tf.reshape(self.h_pool, [-1, num_filters_total], name="hidden_feature")#num_filters_total=256

                ###多层感知机(MLP)是多层感知机
                with tf.name_scope("MLP"):
                    W0 = tf.Variable(tf.truncated_normal([num_filters_total, num_filters_total], stddev=0.1), name="W0")#[256,256]
                    b0 = tf.Variable(tf.constant(0.1, shape=[num_filters_total]), name="b0")#256
                    h0 = tf.nn.relu(tf.nn.xw_plus_b(self.h_pool_flat, W0, b0))
                    W1 = tf.Variable(tf.truncated_normal([num_filters_total, num_filters_total], stddev=0.1), name="W1")
                    b1 = tf.Variable(tf.constant(0.1, shape=[num_filters_total]), name="b1")
                    self.h1 = tf.nn.relu(tf.nn.xw_plus_b(h0, W1, b1))#[?,256]

                with tf.name_scope("dropout"):
                    self.h1 = tf.nn.dropout(self.h1, self.dropout_keep_prob)

                with tf.name_scope("output"):
                    W = tf.get_variable(
                        "W",
                        shape=[num_filters_total, num_classes],#[256,53]
                        initializer=tf.contrib.layers.xavier_initializer())
                    b = tf.Variable(tf.constant(0.1, shape=[num_classes]), name="b")#num_classes=53
                    self.scores = tf.nn.xw_plus_b(self.h1, W, b, name="scores")

    def Cnnblock(self, num_filters, h, i, has_se=True):
        W1 = tf.get_variable(
            "W1_"+str(i),
            #[3,1,128,128]
            shape=[3, 1, num_filters, num_filters],
            initializer=tf.contrib.layers.xavier_initializer_conv2d())
        b1 = tf.Variable(tf.constant(0.1, shape=[num_filters]), name="b1_"+str(i))
        conv1 = tf.nn.conv2d(
            h,
            W1,
            strides=[1, 1, 1, 1],
            padding="SAME")

        c_ = {'use_bias': True, 'is_training': self.is_training}
        conv1 = self.bn(conv1, c_, str(i) + '-conv1')

        beta1 = tf.Variable(tf.truncated_normal([1], stddev=0.08), name='swish-beta-{}-1'.format(i))
        x1 = tf.nn.bias_add(conv1, b1)
        h1 = x1 * tf.nn.sigmoid(x1 * beta1)

        W2 = tf.get_variable(
            "W2_"+str(i),
            shape=[3, 1, num_filters, num_filters],
            initializer=tf.contrib.layers.xavier_initializer_conv2d())
        b2 = tf.Variable(tf.constant(0.1, shape=[num_filters]), name="b2_"+str(i))
        conv2 = tf.nn.conv2d(
            h1,
            W2,
            strides=[1, 1, 1, 1],
            padding="SAME")

        conv2 = self.bn(conv2, c_, str(i) + '-conv2')

        beta2 = tf.Variable(tf.truncated_normal([1], stddev=0.08), name='swish-beta-{}-2'.format(i))
        x2 = tf.nn.bias_add(conv2, b2)
        h2 = x2 * tf.nn.sigmoid(x2 * beta2)

        if has_se:
            h2 = self.Squeeze_excitation_layer(h2, num_filters, 16, 'se-block-' + str(i))

        return h2

    def bn(self, x, c, name):
        x_shape = x.get_shape()
        params_shape = x_shape[-1:]

        if c['use_bias']:
            bias = self._get_variable('bn_bias_{}'.format(name), params_shape,
                                      initializer=tf.zeros_initializer)
            return x + bias

        axis = list(range(len(x_shape) - 1))
        beta = self._get_variable('bn_beta_{}'.format(name),
                                  params_shape,
                                  initializer=tf.zeros_initializer)
        gamma = self._get_variable('bn_gamma_{}'.format(name),
                                   params_shape,
                                   initializer=tf.ones_initializer)
        moving_mean = self._get_variable('bn_moving_mean_{}'.format(name), params_shape,
                                         initializer=tf.zeros_initializer,
                                         trainable=False)
        moving_variance = self._get_variable('bn_moving_variance_{}'.format(name),
                                             params_shape,
                                             initializer=tf.ones_initializer,
                                             trainable=False)
        # These ops will only be preformed when training.
        mean, variance = tf.nn.moments(x, axis)
        update_moving_mean = moving_averages.assign_moving_average(moving_mean,
                                                                   mean, BN_DECAY)
        update_moving_variance = moving_averages.assign_moving_average(
            moving_variance, variance, BN_DECAY)
        tf.add_to_collection(UPDATE_OPS_COLLECTION, update_moving_mean)
        tf.add_to_collection(UPDATE_OPS_COLLECTION, update_moving_variance)

        mean, variance = control_flow_ops.cond(
            c['is_training'], lambda: (mean, variance),
            lambda: (moving_mean, moving_variance))

        x = tf.nn.batch_normalization(x, mean, variance, beta, gamma, BN_EPSILON)

        return x

    def _get_variable(self, name,
                      shape,
                      initializer,
                      weight_decay=0.0,
                      dtype='float',
                      trainable=True):
        if weight_decay > 0:
            regularizer = tf.contrib.layers.l2_regularizer(weight_decay)
        else:
            regularizer = None
        collections = [tf.GraphKeys.GLOBAL_VARIABLES, RESNET_VARIABLES]
        return tf.get_variable(name,
                               shape=shape,
                               initializer=initializer,
                               dtype=dtype,
                               regularizer=regularizer,
                               collections=collections,
                               trainable=trainable)

    def Squeeze_excitation_layer(self, input_x, out_dim, ratio, layer_name):
        #input_x=[?,98,1,128],out_dim=128,ratio=16,layer_name)='se-block-'
        with tf.name_scope(layer_name):
            squeeze = self.Global_Average_Pooling(input_x)
            #平均池化，在每个通道上求平均，[?,98,1,128]变成，[?,128]
            # #由[?,128]变成[?,8]
            excitation = self.Fully_connected(squeeze, units=out_dim / ratio,#128/16=8
                                              layer_name=layer_name + '_fully_connected1')
            excitation = self.Relu(excitation)
            #又[?,8]变成[?,128]  
            excitation = self.Fully_connected(excitation, units=out_dim,#out_dim=128
                                              layer_name=layer_name + '_fully_connected2')           
            excitation = self.Sigmoid(excitation)
            #每个词的权重都是独立的，每个通道上的权重。不像softmax和为1
            excitation = tf.reshape(excitation, [-1, 1, 1, out_dim])
            #[-1,1,1,128]
            scale = input_x * excitation#[?,98,1,128]*[-1,1,1,128]#相当于在每个通道上加权重。

            return scale

    def Global_Average_Pooling(self, x):
        return global_avg_pool(x, name='Global_avg_pooling')

    def Relu(self, x):
        return tf.nn.relu(x)

    def Sigmoid(self, x):
        return tf.nn.sigmoid(x)

    def Fully_connected(self, x, units, layer_name='fully_connected'):
        with tf.name_scope(layer_name):
            return tf.layers.dense(inputs=x, use_bias=True, units=units)#units=8=128/16
            #这里就是WX+b,输出是8维的，
            #由[?,128]变成[?,8]




class InputExample(object):
    """A single training/test example for simple sequence classification."""
    def __init__(self, guid, text_a, text_b=None, label=None):
        """Constructs a InputExample.

        Args:
          guid: Unique id for the example.
          text_a: string. The untokenized text of the first sequence. For single
            sequence tasks, only this sequence must be specified.
          text_b: (Optional) string. The untokenized text of the second sequence.
            Only must be specified for sequence pair tasks.
          label: (Optional) string. The label of the example. This should be
            specified for train and dev examples, but not for test examples.
        """
        self.guid = guid
        self.text_a = text_a
        self.text_b = text_b
        self.label = label


class InputFeatures(object):
    """A single set of features of data."""

    def __init__(self, input_ids, input_mask, segment_ids, label_id):
        self.input_ids = input_ids
        self.input_mask = input_mask
        self.segment_ids = segment_ids
        self.label_id = label_id


class DataProcessor(object):
    """Base class for data converters for sequence classification data sets."""

    def get_train_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the train set."""
        raise NotImplementedError()

    def get_dev_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the dev set."""
        raise NotImplementedError()

    def get_test_examples(self, data_dir):
        """Gets a collection of `InputExample`s for prediction."""
        raise NotImplementedError()

    def get_labels(self):
        """Gets the list of labels for this data set."""
        raise NotImplementedError()

    @classmethod
    def _read_tsv(cls, input_file, quotechar=None):
        """Reads a tab separated value file."""
        with tf.gfile.Open(input_file, "r") as f:
            reader = csv.reader(f, delimiter="\t", quotechar=quotechar)
            lines = []
            for line in reader:
                lines.append(line)
        return lines


class MultiLabelClassifyProcessor(DataProcessor):

    def __init__(self):
        label_list = []
        start,end = 0,20
        if FLAGS.num_aspects == 20:
            start = 1
            end = 21
        elif FLAGS.num_aspects == 21:
            start = 0
            end = 21
        for i in range(start,end):
            label_list.append(FLAGS.tag_flag+str(i))
        self.label_list = label_list

    def _read_json(self,file_list):
        texts, labels = [], []
        add_labels = self.label_list[10:]
        tf.logging.info("FLAGS.add_part:%s" % FLAGS.add_part)
        add_count = 0
        for file in file_list:
            f = open(file,"r",encoding="utf-8")
            for line in f:
                case = json.loads(line)
                for j, item in enumerate(case):
                    if file.__contains__("add") and FLAGS.add_part:
                        tmp = [l for l in add_labels if l in item["labels"]]
                        if len(tmp) == 0:
                            continue
                        else:
                            add_count += 1
                    texts.append(str(item["sentence"]))
                    labels.append(item["labels"])
        #random.shuffle(kong_biao_qian_all)
        tf.logging.info("add count: %s" % add_count)
        if FLAGS.do_eval:
            train_size = 0.99
        else:
            train_size = 1.0
        X_train, X_test, y_train, y_test = train_test_split(texts, labels, train_size=train_size, random_state=12)
        return {"train":zip(y_train,X_train),"dev":zip(y_test,X_test)}

    def get_examples(self, data_dir,train_data_files):
        tf.logging.info("train_data_files:%s" %train_data_files)
        files = str(train_data_files).strip().split(",")
        file_list = [os.path.join(data_dir,file) for file in files]
        data_set = self._read_json(file_list)
        return self._create_examples(data_set["train"], "train"),self._create_examples(data_set["dev"], "dev")

    def get_test_example(self, input_list):
        return self._create_examples(input_list, 'test')

    def get_labels(self):
        return self.label_list

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            guid = "%s-%s" % (set_type, i)
            # label = tokenization.convert_to_unicode(line[0])
            label = line[0]
            text_a = tokenization.convert_to_unicode(line[1])
            if len(label) == 0 and isinstance(label,str):
                label = []
            examples.append(
              InputExample(guid=guid, text_a=text_a, text_b=None, label=label))
        return examples


class Judger:
    # Initialize Judger, with the path of tag list
    def __init__(self, tag_path):
        self.tag_dic = {}
        f = open(tag_path, "r", encoding='utf-8')
        self.task_cnt = 0
        for line in f:
            self.task_cnt += 1
            self.tag_dic[line[:-1]] = self.task_cnt


    # Format the result generated by the Predictor class
    @staticmethod
    def format_result(result):
        rex = {"tags": []}
        res_art = []
        for x in result["tags"]:
            if not (x is None):
                res_art.append(int(x))
        rex["tags"] = res_art

        return rex

    # Gen new results according to the truth and users output
    def gen_new_result(self, result, truth, label):

        s1 = set()
        for tag in label:
            s1.add(self.tag_dic[tag.replace(' ', '')])
        s2 = set()
        for name in truth:
            s2.add(self.tag_dic[name.replace(' ', '')])

        for a in range(0, self.task_cnt):
            in1 = (a + 1) in s1
            in2 = (a + 1) in s2
            if in1:
                if in2:
                    result[0][a]["TP"] += 1
                else:
                    result[0][a]["FP"] += 1
            else:
                if in2:
                    result[0][a]["FN"] += 1
                else:
                    result[0][a]["TN"] += 1

        return result

    @staticmethod
    def get_value(res):
        if res["TP"] == 0:
            if res["FP"] == 0 and res["FN"] == 0:
                precision = 1.0
                recall = 1.0
                f1 = 1.0
            else:
                precision = 0.0
                recall = 0.0
                f1 = 0.0
        else:
            precision = 1.0 * res["TP"] / (res["TP"] + res["FP"])
            recall = 1.0 * res["TP"] / (res["TP"] + res["FN"])
            f1 = 2 * precision * recall / (precision + recall)

        return precision, recall, f1

    # Generate score
    def gen_score(self, arr):
        sumf = 0
        y = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
        for x in arr[0]:
            p, r, f = self.get_value(x)
            sumf += f
            for z in x.keys():
                y[z] += x[z]

        _, __, f_ = self.get_value(y)
        tf.logging.info("微平均f_:%s ;宏平均sumf:%s " %(f_,sumf* 1.0 / len(arr[0])))
        return (f_ + sumf * 1.0 / len(arr[0])) / 2.0

    # Test with ground truth path and the user's output path
    def test(self, truth_path, output_path):
        cnt = 0
        result = [[]]
        for a in range(0, self.task_cnt):
            result[0].append({"TP": 0, "FP": 0, "TN": 0, "FN": 0})

        with open(truth_path, "r", encoding='utf-8') as inf, open(output_path, "r", encoding='utf-8') as ouf:
            for line in inf:
                ground_doc = json.loads(line)
                user_doc = json.loads(ouf.readline())
                for ind in range(len(ground_doc)):
                    ground_truth = ground_doc[ind]['labels']
                    user_output = user_doc[ind]['labels']
                    cnt += 1
                    result = self.gen_new_result(result, ground_truth, user_output)
        return result


def convert_single_example(ex_index, example, label_list, max_seq_length,
                           tokenizer):
    tokens_a = tokenizer.tokenize(example.text_a)
    tokens_b = None
    if example.text_b:
        tokens_b = tokenizer.tokenize(example.text_b)

    if tokens_b:
        # Modifies `tokens_a` and `tokens_b` in place so that the total
        # length is less than the specified length.
        # Account for [CLS], [SEP], [SEP] with "- 3"
        _truncate_seq_pair(tokens_a, tokens_b, max_seq_length - 3)
    else:
        # Account for [CLS] and [SEP] with "- 2"
        if len(tokens_a) > max_seq_length - 2:
            tokens_a = tokens_a[0:(max_seq_length - 2)]

    tokens = []
    segment_ids = []
    tokens.append("[CLS]")
    segment_ids.append(0)
    for token in tokens_a:
        tokens.append(token)
        segment_ids.append(0)
    tokens.append("[SEP]")
    segment_ids.append(0)

    if tokens_b:
        for token in tokens_b:
            tokens.append(token)
            segment_ids.append(1)
        tokens.append("[SEP]")
        segment_ids.append(1)

    input_ids = tokenizer.convert_tokens_to_ids(tokens)

    # The mask has 1 for real tokens and 0 for padding tokens. Only real
    # tokens are attended to.
    input_mask = [1] * len(input_ids)

    # Zero-pad up to the sequence length.
    while len(input_ids) < max_seq_length:
        input_ids.append(0)
        input_mask.append(0)
        segment_ids.append(0)

    assert len(input_ids) == max_seq_length
    assert len(input_mask) == max_seq_length
    assert len(segment_ids) == max_seq_length
    # print("label_map:",label_map,";length of label_map:",len(label_map))
    # convert to multi-hot style
    label_id = [0 for l in range(len(label_list))]
    # get list of label
    # print("example.label:",example.label)
    if len(example.label) != 0:
        label_id_list = example.label
        # print("label_id_list:", label_id_list)
        for label_ in label_id_list:
            label_id[label_list.index(label_)] = 1

    feature = InputFeatures(
                input_ids=input_ids,
                input_mask=input_mask,
                segment_ids=segment_ids,
                label_id=label_id)
    return feature


def file_based_convert_examples_to_features(
    examples, label_list, max_seq_length, tokenizer, output_file):
    """Convert a set of `InputExample`s to a TFRecord file."""
    writer = tf.python_io.TFRecordWriter(output_file)

    for (ex_index, example) in enumerate(examples):
        if ex_index % 10000 == 0:
            tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

        feature = convert_single_example(ex_index, example, label_list,
                                         max_seq_length, tokenizer)

        def create_int_feature(values):
            f = tf.train.Feature(int64_list=tf.train.Int64List(value=list(values)))
            return f

        features = collections.OrderedDict()
        features["input_ids"] = create_int_feature(feature.input_ids)
        features["input_mask"] = create_int_feature(feature.input_mask)
        features["segment_ids"] = create_int_feature(feature.segment_ids)

        # if feature.label_id is already a list, then no need to add [].
        if isinstance(feature.label_id, list):
            label_ids=feature.label_id
        else:
            label_ids = [feature.label_id]
        features["label_ids"] = create_int_feature(label_ids)


        tf_example = tf.train.Example(features=tf.train.Features(feature=features))
        writer.write(tf_example.SerializeToString())



def file_based_input_fn_builder(input_file, seq_length, is_training,
                                drop_remainder):
    """Creates an `input_fn` closure to be passed to TPUEstimator."""
    # task specific parameter
    name_to_features = {
      "input_ids": tf.FixedLenFeature([seq_length], tf.int64),
      "input_mask": tf.FixedLenFeature([seq_length], tf.int64),
      "segment_ids": tf.FixedLenFeature([seq_length], tf.int64),
      "label_ids": tf.FixedLenFeature([FLAGS.num_aspects], tf.int64), # ADD TO A FIXED LENGTH
    }

    def _decode_record(record, name_to_features):
        """Decodes a record to a TensorFlow example."""
        example = tf.parse_single_example(record, name_to_features)

        # tf.Example only supports tf.int64, but the TPU only supports tf.int32.
        # So cast all int64 to int32.
        for name in list(example.keys()):
            t = example[name]
            if t.dtype == tf.int64:
                t = tf.to_int32(t)
            example[name] = t
        return example

    def input_fn(params):
        """The actual input function."""
        batch_size = params["batch_size"]
        tf.logging.info("batch_size 888: %s" % batch_size)

        # For training, we want a lot of parallel reading and shuffling.
        # For eval, we want no shuffling and parallel reading doesn't matter.
        d = tf.data.TFRecordDataset(input_file)
        if is_training:
            d = d.repeat()
            d = d.shuffle(buffer_size=100)

        d = d.apply(
            tf.contrib.data.map_and_batch(
                lambda record: _decode_record(record, name_to_features),
                batch_size=batch_size,
                drop_remainder=drop_remainder))
        return d
    return input_fn


def _truncate_seq_pair(tokens_a, tokens_b, max_length):
    """Truncates a sequence pair in place to the maximum length."""

    # This is a simple heuristic which will always truncate the longer sequence
    # one token at a time. This makes more sense than truncating an equal percent
    # of tokens from each, since if one sequence is very short then each token
    # that's truncated likely contains more information than a longer sequence.
    while True:
        total_length = len(tokens_a) + len(tokens_b)
        if total_length <= max_length:
            break
        if len(tokens_a) > len(tokens_b):
            tokens_a.pop()
        else:
            tokens_b.pop()

'''
def create_model_original(bert_config, is_training, input_ids, input_mask, segment_ids,
                 labels, num_labels, use_one_hot_embeddings):
    """Creates a classification model."""
    model = modeling.BertModel(
            config=bert_config,
            is_training=is_training,
            input_ids=input_ids,
            input_mask=input_mask,
            token_type_ids=segment_ids,
            use_one_hot_embeddings=use_one_hot_embeddings)

    # In the demo, we are doing a simple classification task on the entire
    # segment.
    #
    # If you want to use the token-level output, use model.get_sequence_output()
    # instead.
    output_layer = model.get_pooled_output() # 从主干模型获得模型的输出
    
    hidden_size = output_layer.shape[-1].value

    output_weights = tf.get_variable( # 分类模型特有的分类层的参数
      "output_weights", [num_labels, hidden_size],
      initializer=tf.truncated_normal_initializer(stddev=0.02))
    
    output_bias = tf.get_variable( # 分类模型特有的bias
      "output_bias", [num_labels], initializer=tf.zeros_initializer())

    with tf.variable_scope("loss"):
        if is_training:
            output_layer = tf.nn.dropout(output_layer, keep_prob=0.9)
        
        logits = tf.matmul(output_layer, output_weights, transpose_b=True) # 分类模型特有的分类层
        logits = tf.nn.bias_add(logits, output_bias)
        probabilities = tf.nn.softmax(logits, axis=-1)
        log_probs = tf.nn.log_softmax(logits, axis=-1)
        one_hot_labels = tf.one_hot(labels, depth=num_labels, dtype=tf.float32)
        per_example_loss = -tf.reduce_sum(one_hot_labels * log_probs, axis=-1) # 利用交叉熵就和
        loss = tf.reduce_mean(per_example_loss)
        
        return (loss, per_example_loss, logits, probabilities)

'''


def create_model(bert_config, is_training, input_ids, input_mask, segment_ids,
                 labels, num_labels, use_one_hot_embeddings):
    """Creates a classification model."""
    model = modeling.BertModel(
      config=bert_config,
      is_training=is_training,
      input_ids=input_ids,
      input_mask=input_mask,
      token_type_ids=segment_ids,
      use_one_hot_embeddings=use_one_hot_embeddings)

    bert_hx= model.get_pooled_output() # 合并的从主干模型获得模型的输出[32,768]
    tf.logging.info('reshape后的大小: %s' % bert_hx.shape)

    bert_output = model.get_sequence_output() # 获取字向量的结果[32,128,768]
    tf.logging.info('reshape后的大小: %s' % bert_output.shape)

    #Dcnn部分
    bert_out_expanded = tf.expand_dims(bert_output, -1)
    #(32, 128, 768, 1)
    tf.logging.info('bert_out_expanded后的大小: %s' % bert_out_expanded.shape)
    embedding_size=bert_output.shape[-1].value 
    SE_Res_scores = RECnn(
            FLAGS.max_seq_length,#128
            num_classes=20,#53
            embedding_size=768,#768
            # list(map(int, FLAGS.filter_sizes.split(","))),#filter_sizes=3
            filter_sizes=[3,4,5],
            num_filters=FLAGS.num_filters,#128
            embedded_chars_expanded=bert_out_expanded,
            dropout_keep_prob = 0.8,
            is_training=True)
    #SE_Res_scores.scores=[32,20]
    tf.logging.info('SE_Res_scores后的大小: %s' % SE_Res_scores.scores.shape)
    tf.logging.info('h_pool后的大小: %s' % SE_Res_scores.h_pool.shape)
    tf.logging.info('h_pool在reshape后的大小: %s' % SE_Res_scores.h_pool_flat.shape)

    # embedding_size=bert_output.shape[-1].value

    # #2. CONVOLUTION LAYER + MAXPOOLING LAYER (per filter) ###############################
    # filter_sizes = [3,4,5]
    # pooled_outputs = []
    # for i, filter_size in enumerate(filter_sizes):
    #     with tf.name_scope("conv-maxpool-%s" % filter_size):
    #         # CONVOLUTION LAYER
    #         filter_shape = [filter_size, embedding_size, 1, FLAGS.num_filters]
    #         W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")
    #         b = tf.Variable(tf.constant(0.1, shape=[FLAGS.num_filters]), name="b")
    #         conv = tf.nn.conv2d(bert_out_expanded, W,strides=[1, 1, 1, 1],padding="VALID",name="conv")
    #         # NON-LINEARITY
    #         h = tf.nn.relu(tf.nn.bias_add(conv, b), name="relu")
    #         # MAXPOOLING
    #         pooled = tf.nn.max_pool(h, ksize=[1, FLAGS.max_seq_length - filter_size + 1, 1, 1], strides=[1, 1, 1, 1], padding='VALID', name="pool")
    #         pooled_outputs.append(pooled)

    #     # COMBINING POOLED FEATURES
    # num_filters_total = FLAGS.num_filters * len(filter_sizes)
    # h_pool = tf.concat(pooled_outputs, 3)
    # h_pool_flat = tf.reshape(h_pool, [-1, num_filters_total])
    # tf.logging.info('3_CNN_reshape后的大小: %s' % h_pool_flat.shape)
        
    #     # #3. DROPOUT LAYER ###################################################################
    # with tf.name_scope("dropout"):
    #     h_drop = tf.nn.dropout(h_pool_flat, FLAGS.cnn_dropout)
    # tf.logging.info('CNN_drop后的大小: %s' % h_drop.shape)
    # with tf.name_scope("score_cnn"):
    #     logits_cnn = tf.layers.dense(h_drop, num_labels, name='h_drop_cnn')##相当于reshape
    # tf.logging.info('CNN_drop后的大小: %s' % logits_cnn.shape)

    with tf.name_scope("rnn_attention"):
        hidden_size = bert_output.shape[2].value  # D value - hidden size of the RNN layer
        # 128，是RNN内部隐藏层的神经元个数。
        # inputs=[?, 100, 128] 每个时刻的双层GRU的输出，

        # Trainable parameters
        w_omega = tf.Variable(tf.random_normal([hidden_size*2, FLAGS.attention_size], stddev=0.1))  # W=[128,50]
        b_omega = tf.Variable(tf.random_normal([FLAGS.attention_size], stddev=0.1))  # b=[50]
        u_omega = tf.Variable(tf.random_normal([FLAGS.attention_size], stddev=0.1))  # U=[50,]

        batch_=tf.concat([bert_output,tf.tile(tf.expand_dims(bert_hx,1),[1,FLAGS.max_seq_length,1])],2)
        #tf.expand_dims(hx,1)在[?,128]中间加一个维度，变成[?,1,128]
        #tf.tile(tf.expand_dims(hx,1),[1,self.config.seq_length,1])-复制最后一个时刻的输出[?,1,128]变成[?,200,128]
        #batch_=[?,200,256]加上了最后时刻的效果的累加。

        with tf.name_scope('v'):
            # Applying fully connected layer with non-linear activation to each of the B*T timestamps;
            #  the shape of `v` is (B,T,D)*(D,A)=(B,T,A), where A=attention_size
            v = tf.tanh(tf.tensordot(batch_, w_omega, axes=1) + b_omega)
            #tf.einsum('ijm,mn->ijn', inputs, w_omega)
            
        # For each of the timestamps its vector of size A from `v` is reduced with `u` vector
        # 对于每个时间戳，其大小为A的向量从' v '被' u '向量约简
        vu = tf.tensordot(v, u_omega, axes=1, name='vu')  # (B,T) shape
        # [?, 100]
        alphas = tf.nn.softmax(vu, name='alphas')  # 归一化       # (B,T) shape

        # Output of (Bi-)RNN is reduced with attention vector; the result has (B,D) shape
        # [?, 100, 128] * [?, 100, 1] ==>> [?, 100, 128] ==>> [?, 128]
        bert_attention_output = tf.reduce_sum(bert_output * tf.expand_dims(alphas, -1), 1)

        with tf.name_scope("rnn_score"):
            fc = tf.layers.dense(bert_attention_output, FLAGS.hidden_dim, name='fc1')
            fc = tf.contrib.layers.dropout(fc, FLAGS.rnn_dropout)
            fc = tf.nn.relu(fc)
            
            # [?, 20] 分类置信度
            logits_rnn = tf.layers.dense(fc, num_labels, name='fc2')

        
        combine_logits = SE_Res_scores.scores + logits_rnn

            
       
    with tf.variable_scope("loss"):
        labels = tf.cast(labels,tf.float32)
        cross_entropy = tf.nn.sigmoid_cross_entropy_with_logits(logits=combine_logits, labels=labels)
        #losses = tf.reduce_mean(tf.reduce_sum(cross_entropy, axis=1))
        losses = tf.reduce_mean(cross_entropy)
        y_pred_cls = tf.sigmoid(combine_logits, name="scores")

    return losses,cross_entropy,combine_logits,y_pred_cls




    # hidden_size = embedded.shape[-1].value#[32,128,768]
    # tf.logging.info("output_layer:%s" % embedded.shape)

    #添加lstm层
    # from bert_base.train.lstm_crf_layer import BLSTM_CRF
    # from tensorflow.contrib.layers.python.layers import initializers
    # used = tf.sign(tf.abs(input_ids))
    # lengths = tf.reduce_sum(used, reduction_indices=1)  # [batch_size] 大小的向量，包含了当前batch中的序列长度
    # tf.logging.info("lengths:%s" % lengths)
    # blstm_crf = BLSTM_CRF(embedded_chars=embedded, hidden_unit=hidden_size, cell_type='lstm', num_layers=3,
    #                   dropout_rate=1.0, initializers=initializers, num_labels=num_labels,
    #                   seq_length=FLAGS.max_seq_length, labels=labels, lengths=lengths,
    #                   is_training=is_training)
    # output_layer = blstm_crf.blstm_layer(blstm_crf.embedded_chars)
    # #[32,128,1536]

    # tf.logging.info("加入lstm后的大小：%s" % output_layer.shape)

    # output_layer = tf.reshape(output_layer, shape=[-1, output_layer.shape[1].value*output_layer.shape[2].value])
    # #[32,196608]=128*1536

    # tf.logging.info('reshape后的大小: %s' % output_layer.shape)

    # output_weights = tf.get_variable( # 分类模型特有的分类层的参数
    #                 "output_weights", [num_labels, output_layer.shape[-1].value],#[20,196608],后面变成20个类别的输出。
    #                 initializer=tf.truncated_normal_initializer(stddev=0.02))
    # #
    # output_bias = tf.get_variable( # 分类模型特有的bias
    #                 "output_bias", [num_labels], initializer=tf.zeros_initializer())

    # with tf.variable_scope("loss"):
    #     if is_training:
    #         output_layer = tf.nn.dropout(output_layer, keep_prob=0.9)

    #     logits = tf.matmul(output_layer, output_weights, transpose_b=True) # 分类模型特有的分类层
        


    #     logits = tf.nn.bias_add(logits, output_bias)

    #     probabilities = tf.nn.sigmoid(logits)
    #     labels = tf.cast(labels,tf.float32)

    #     tf.logging.info("num_labels:%s ;logits:%s ;labels: %s" %(num_labels, logits, labels))
    #     per_example_loss = tf.nn.sigmoid_cross_entropy_with_logits(labels=labels, logits=logits)
    #     loss = tf.reduce_mean(per_example_loss)

    #     return (loss, per_example_loss, logits, probabilities)


def model_fn_builder(bert_config, num_labels, init_checkpoint, learning_rate,
                     num_train_steps, num_warmup_steps, use_tpu,
                     use_one_hot_embeddings):
    """Returns `model_fn` closure for TPUEstimator."""

    def model_fn(features, labels, mode, params):  # pylint: disable=unused-argument
        """The `model_fn` for TPUEstimator."""

        tf.logging.info("*** Features ***")
        for name in sorted(features.keys()):
            tf.logging.info("  name = %s, shape = %s" % (name, features[name].shape))

        input_ids = features["input_ids"]
        input_mask = features["input_mask"]
        segment_ids = features["segment_ids"]
        label_ids = features["label_ids"]
        is_real_example = None
        if "is_real_example" in features:
            is_real_example = tf.cast(features["is_real_example"], dtype=tf.float32)
        else:
            is_real_example = tf.ones(tf.shape(label_ids), dtype=tf.float32)

        is_training = (mode == tf.estimator.ModeKeys.TRAIN)

        (total_loss, per_example_loss, logits, probabilities) = create_model(
            bert_config, is_training, input_ids, input_mask, segment_ids, label_ids,
            num_labels, use_one_hot_embeddings)

        tvars = tf.trainable_variables()

        scaffold_fn = None
        if init_checkpoint:
            (assignment_map, initialized_variable_names
            ) = modeling.get_assignment_map_from_checkpoint(tvars, init_checkpoint)
            if use_tpu:
                def tpu_scaffold():
                    tf.train.init_from_checkpoint(init_checkpoint, assignment_map)
                    return tf.train.Scaffold()
                scaffold_fn = tpu_scaffold
            else:
                tf.train.init_from_checkpoint(init_checkpoint, assignment_map)

        
        # tf.logging.info("**** Trainable Variables ****")
        # for var in tvars:
        #     init_string = ""
        #     if var.name in initialized_variable_names:
        #         init_string = ", *INIT_FROM_CKPT*"
        #     tf.logging.info("  name = %s, shape = %s%s", var.name, var.shape,init_string) 

        output_spec = None
        if mode == tf.estimator.ModeKeys.TRAIN:

            train_op = optimization.create_optimizer(
              total_loss, learning_rate, num_train_steps, num_warmup_steps, use_tpu)

            logging_hook = tf.train.LoggingTensorHook({"loss": total_loss}, every_n_iter=100)
            output_spec = tf.contrib.tpu.TPUEstimatorSpec(
                            mode=mode,
                            loss=total_loss,
                            train_op=train_op,
                            #training_hooks=[logging_hook],
                            scaffold_fn=scaffold_fn)
        elif mode == tf.estimator.ModeKeys.EVAL:
            def metric_fn(per_example_loss, label_ids, probabilities, is_real_example):
                logits_split = tf.split(probabilities, num_labels, axis=-1)
                label_ids_split = tf.split(label_ids, num_labels, axis=-1)
                # metrics change to auc of every class
                eval_dict = {}
                #print(type(probabilities))
                for j, logits in enumerate(logits_split):
                    label_id_ = tf.cast(label_ids_split[j], dtype=tf.int32)
                    current_auc, update_op_auc = tf.metrics.auc(label_id_, logits)
                    eval_dict[str(j)] = (current_auc, update_op_auc)
                eval_dict['eval_loss'] = tf.metrics.mean(values=per_example_loss)
                return eval_dict
            eval_metrics = (metric_fn, [per_example_loss, label_ids, probabilities,is_real_example])
            #eval_metrics = [metric_fn(per_example_loss, label_ids, logits,is_real_example)
            output_spec = tf.contrib.tpu.TPUEstimatorSpec(
                  mode=mode,
                  loss=total_loss,
                  eval_metrics=eval_metrics,
                  scaffold_fn=scaffold_fn)
        else:
            output_spec = tf.contrib.tpu.TPUEstimatorSpec(
                        mode=mode, predictions=probabilities, scaffold_fn=scaffold_fn)
        return output_spec

    return model_fn


# This function is not used by this file but is still used by the Colab and
# people who depend on it.
def input_fn_builder(features, label_list, seq_length, is_training):
    """Creates an `input_fn` closure to be passed to TPUEstimator."""

    all_input_ids = []
    all_input_mask = []
    all_segment_ids = []
    all_label_ids = []
    for feature in features:
        all_input_ids.append(feature.input_ids)
        all_input_mask.append(feature.input_mask)
        all_segment_ids.append(feature.segment_ids)
        all_label_ids.append(feature.label_id)

    def input_fn(params):
        """The actual input function."""
        batch_size = params["batch_size"]
        num_examples = len(features)
        num_labels = len(label_list)
        d = tf.data.Dataset.from_tensor_slices({
            "input_ids":
                tf.constant(
                    all_input_ids, shape=[num_examples, seq_length],
                    dtype=tf.int32),
            "input_mask":
                tf.constant(
                    all_input_mask,
                    shape=[num_examples, seq_length],
                    dtype=tf.int32),
            "segment_ids":
                tf.constant(
                    all_segment_ids,
                    shape=[num_examples, seq_length],
                    dtype=tf.int32),
            "label_ids":
                tf.constant(all_label_ids,
                            shape=[num_examples, num_labels],
                            dtype=tf.int32),
        })
        if is_training:
            d = d.repeat()
            d = d.shuffle(buffer_size=100)

        d = d.batch(batch_size=batch_size)
        return d
    return input_fn


# This function is not used by this file but is still used by the Colab and
# people who depend on it.
def convert_examples_to_features(examples, label_list, max_seq_length,
                                 tokenizer):
    """Convert a set of `InputExample`s to a list of `InputFeatures`."""

    features = []
    for (ex_index, example) in enumerate(examples):
        if ex_index % 10000 == 0:
            tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

        feature = convert_single_example(ex_index, example, label_list,
                                     max_seq_length, tokenizer)
        features.append(feature)
    return features


def get_single_score(truth_path, output_path, tag_path):
    judger = Judger(tag_path=tag_path)
    reslt = judger.test(truth_path=truth_path,output_path=output_path)
    score = judger.gen_score(reslt)
    tf.logging.info("output_path:%s" % output_path)
    tf.logging.info('predict score:%s' % score)
    return score

def main(_):
    tf.logging.set_verbosity(tf.logging.INFO)

    processors = {
      "multi_label":MultiLabelClassifyProcessor,
    }

    if not FLAGS.do_train and not FLAGS.do_eval and not FLAGS.do_predict:
        raise ValueError(
                "At least one of `do_train`, `do_eval` or `do_predict' must be True.")

    bert_config = modeling.BertConfig.from_json_file(FLAGS.bert_config_file)

    if FLAGS.max_seq_length > bert_config.max_position_embeddings:
        raise ValueError(
                "Cannot use sequence length %d because the BERT model "
                "was only trained up to sequence length %d" %
                (FLAGS.max_seq_length, bert_config.max_position_embeddings))

    tf.gfile.MakeDirs(FLAGS.output_dir)

    task_name = FLAGS.task_name.lower()

    if task_name not in processors:
        raise ValueError("Task not found: %s" % (task_name))

    processor = processors[task_name]()

    label_list = processor.get_labels()

    tokenizer = tokenization.FullTokenizer(
                vocab_file=FLAGS.vocab_file, do_lower_case=FLAGS.do_lower_case)

    tpu_cluster_resolver = None
    if FLAGS.use_tpu and FLAGS.tpu_name:
        tpu_cluster_resolver = tf.contrib.cluster_resolver.TPUClusterResolver(
                                FLAGS.tpu_name, zone=FLAGS.tpu_zone, project=FLAGS.gcp_project)

    is_per_host = tf.contrib.tpu.InputPipelineConfig.PER_HOST_V2
    run_config = RunConfig(
                    cluster=tpu_cluster_resolver,
                    master=FLAGS.master,
                    #session_config=config,
                    model_dir=FLAGS.output_dir,
                    save_checkpoints_steps=FLAGS.save_checkpoints_steps,
                    tpu_config=TPUConfig(
                                iterations_per_loop=FLAGS.iterations_per_loop,
                                num_shards=FLAGS.num_tpu_cores,
                                per_host_input_for_training=is_per_host))
    train_examples = None
    num_train_steps = None
    num_warmup_steps = None
    eval_examples = None

    if FLAGS.do_train or FLAGS.do_eval:
        train_examples,eval_examples = processor.get_examples(FLAGS.data_dir,FLAGS.train_data_files)

    if FLAGS.do_train:
        # train_examples = processor.get_train_examples(FLAGS.data_dir)
        num_train_steps = int(
            len(train_examples) / FLAGS.train_batch_size * FLAGS.num_train_epochs)
        num_warmup_steps = int(num_train_steps * FLAGS.warmup_proportion)

    model_fn = model_fn_builder(
                bert_config=bert_config,
                num_labels=len(label_list),
                init_checkpoint=FLAGS.init_checkpoint,
                learning_rate=FLAGS.learning_rate,
                num_train_steps=num_train_steps,
                num_warmup_steps=num_warmup_steps,
                use_tpu=FLAGS.use_tpu,
                use_one_hot_embeddings=FLAGS.use_tpu)

    # If TPU is not available, this will fall back to normal Estimator on CPU
    # or GPU.
    estimator = tf.contrib.tpu.TPUEstimator(
                use_tpu=FLAGS.use_tpu,
                model_fn=model_fn,
                config=run_config,
                train_batch_size=FLAGS.train_batch_size,
                eval_batch_size=FLAGS.eval_batch_size,
                predict_batch_size=FLAGS.predict_batch_size)

    if FLAGS.do_train:
        # train_file = os.path.join(FLAGS.output_dir, "train.tf_record")
        features = convert_examples_to_features(
            train_examples, label_list, FLAGS.max_seq_length, tokenizer)
        tf.logging.info("***** Running training *****")
        tf.logging.info("  Num examples = %d", len(train_examples))
        tf.logging.info("  Batch size = %d", FLAGS.train_batch_size)
        tf.logging.info("  Num steps = %d", num_train_steps)
        train_input_fn = input_fn_builder(
            features=features,
            label_list = label_list,
            seq_length=FLAGS.max_seq_length,
            is_training=True)
        estimator.train(input_fn=train_input_fn, max_steps=num_train_steps)

    if FLAGS.do_eval:
        eval_file = os.path.join(FLAGS.output_dir, "eval.tf_record")
        file_based_convert_examples_to_features(
            eval_examples, label_list, FLAGS.max_seq_length, tokenizer, eval_file)

        tf.logging.info("***** Running evaluation *****")
        tf.logging.info("  Num examples = %d", len(eval_examples))
        tf.logging.info("  Batch size = %d", FLAGS.eval_batch_size)

        # This tells the estimator to run through the entire set.
        eval_steps = None
        # However, if running eval on the TPU, you will need to specify the
        # number of steps.
        # if FLAGS.use_tpu:
            # Eval will be slightly WRONG on the TPU because it will truncate
            # the last batch.
        eval_steps = int(len(eval_examples) / FLAGS.eval_batch_size)

        eval_drop_remainder = True if FLAGS.use_tpu else False
        eval_input_fn = file_based_input_fn_builder(
            input_file=eval_file,
            seq_length=FLAGS.max_seq_length,
            is_training=False,
            drop_remainder=eval_drop_remainder)

        result = estimator.evaluate(input_fn=eval_input_fn, steps=eval_steps)

        output_eval_file = os.path.join(FLAGS.output_dir, "eval_results.txt")
        with tf.gfile.GFile(output_eval_file, "w") as writer:
            tf.logging.info("***** Eval results *****")
            for key in sorted(result.keys()):
                tf.logging.info("  %s = %s", key, str(result[key]))
                writer.write("%s = %s\n" % (key, str(result[key])))

    if FLAGS.do_predict:
        output_predict_file = os.path.join(FLAGS.output_dir, "test_results_all_data.tsv")
        with open(os.path.join(FLAGS.data_dir,FLAGS.test_data_file), 'r', encoding='utf-8') as inf, open(os.path.join(FLAGS.output_dir,str(FLAGS.num_aspects)+"_"+FLAGS.tag_flag+"_"+str(FLAGS.rs_flag)+"_test_output.json"), 'w', encoding='utf-8') as outf, tf.gfile.GFile(output_predict_file, "w") as writer:
            split_count,all_data = [],[]
            for line in inf:
                case = json.loads(line)
                input_list = []
                for j, item in enumerate(case):
                    sentence = item["sentence"]
                    input_list.append(('',sentence))
                all_data.extend(input_list)
                split_count.append(len(all_data))

            predict_examples = processor.get_test_example(all_data)
            predict_file = os.path.join(FLAGS.output_dir, "predict.tf_record")
            file_based_convert_examples_to_features(predict_examples, label_list,
                                                    FLAGS.max_seq_length, tokenizer,
                                                    predict_file)
            tf.logging.info("***** Running prediction*****")
            tf.logging.info("  Num examples = %d", len(predict_examples))
            tf.logging.info("  Batch size = %d", FLAGS.predict_batch_size)

            if FLAGS.use_tpu:
                # Warning: According to tpu_estimator.py Prediction on TPU is an
                # experimental feature and hence not supported here
                raise ValueError("Prediction in TPU not supported")

            predict_drop_remainder = True if FLAGS.use_tpu else False
            predict_input_fn = file_based_input_fn_builder(
                                input_file=predict_file,
                                seq_length=FLAGS.max_seq_length,
                                is_training=False,
                                drop_remainder=predict_drop_remainder)

            result = estimator.predict(input_fn=predict_input_fn)
            predict_doc = []
            for i, prediction in enumerate(result):
                output_line = "\t".join(str(class_probability) for class_probability in prediction) + "\n"
                writer.write(output_line)
                if i in split_count:
                    json.dump(predict_doc, outf, ensure_ascii=False)
                    outf.write('\n')
                    predict_doc = []
                temp = []
                for j, rs in enumerate(prediction):
                    if rs > FLAGS.rs_flag:
                        if FLAGS.num_aspects == 20:
                            temp.append(FLAGS.tag_flag + str(j+1))
                        elif FLAGS.num_aspects == 21:
                            temp.append(FLAGS.tag_flag + str(j))
                    zero_label = FLAGS.tag_flag+"0"
                    if zero_label in temp:
                        temp.remove(zero_label)
                predict_doc.append({"sentence":predict_examples[i].text_a,"labels":temp})
            json.dump(predict_doc, outf, ensure_ascii=False)
            outf.write('\n')
        get_single_score(truth_path=os.path.join(FLAGS.data_dir,FLAGS.test_data_file),output_path=os.path.join(FLAGS.output_dir,str(FLAGS.num_aspects)+"_"+FLAGS.tag_flag+"_"+str(FLAGS.rs_flag)+"_test_output.json"),tag_path=os.path.join(FLAGS.data_dir,FLAGS.tag_file))



if __name__ == "__main__":
    flags.mark_flag_as_required("data_dir")
    flags.mark_flag_as_required("train_data_files")
    flags.mark_flag_as_required("output_dir")
    flags.mark_flag_as_required("num_aspects")
    flags.mark_flag_as_required("tag_flag")
    tf.app.run()
