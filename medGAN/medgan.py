import sys, time, argparse
import tensorflow as tf
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from tensorflow.contrib.layers import l2_regularizer
from tensorflow.contrib.layers import batch_norm
from sklearn import linear_model
from sklearn.metrics import f1_score
import matplotlib as plt
import cPickle as pickle

_VALIDATION_RATIO = 0.1


class Medgan(object):
    def __init__(self,
                 dataType='binary',
                 inputDim=615,
                 embeddingDim=128,
                 randomDim=128,
                 generatorDims=(128, 128),
                 discriminatorDims=(256, 128, 1),
                 compressDims=(),
                 decompressDims=(),
                 bnDecay=0.99,
                 l2scale=0.001):
        self.inputDim = inputDim
        self.embeddingDim = embeddingDim
        self.generatorDims = list(generatorDims) + [embeddingDim]
        self.randomDim = randomDim
        self.dataType = dataType

        if dataType == 'binary':
            self.aeActivation = tf.nn.tanh
        else:
            self.aeActivation = tf.nn.relu

        self.generatorActivation = tf.nn.relu
        self.discriminatorActivation = tf.nn.relu
        self.discriminatorDims = discriminatorDims
        self.compressDims = list(compressDims) + [embeddingDim]
        self.decompressDims = list(decompressDims) + [inputDim]
        self.bnDecay = bnDecay
        self.l2scale = l2scale

        dataPath = './PATIENTS.csv.matrix'
        data = np.load(dataPath)
        if self.dataType == 'binary':
            data = np.clip(data, 0, 1)
        self.trainX, self.validX = train_test_split(data, test_size=_VALIDATION_RATIO, random_state=0)

    # def loadData(self, dataPath=''):
    #     data = np.load(dataPath)
    #
    #     if self.dataType == 'binary':
    #         data = np.clip(data, 0, 1)
    #
    #     trainX, validX = train_test_split(data, test_size=_VALIDATION_RATIO, random_state=0)
    #     return trainX, validX

    def buildAutoencoder(self, x_input):
        decodeVariables = {}
        with tf.variable_scope('autoencoder', regularizer=l2_regularizer(self.l2scale)):
            tempVec = x_input
            tempDim = self.inputDim
            i = 0
            for compressDim in self.compressDims:
                W = tf.get_variable('aee_W_'+str(i), shape=[tempDim, compressDim])
                b = tf.get_variable('aee_b_'+str(i), shape=[compressDim])
                tempVec = self.aeActivation(tf.add(tf.matmul(tempVec, W), b))
                tempDim = compressDim
                i += 1
    
            i = 0
            for decompressDim in self.decompressDims[:-1]:
                W = tf.get_variable('aed_W_'+str(i), shape=[tempDim, decompressDim])
                b = tf.get_variable('aed_b_'+str(i), shape=[decompressDim])
                tempVec = self.aeActivation(tf.add(tf.matmul(tempVec, W), b))
                tempDim = decompressDim
                decodeVariables['aed_W_'+str(i)] = W
                decodeVariables['aed_b_'+str(i)] = b
                i += 1
            W = tf.get_variable('aed_W_'+str(i), shape=[tempDim, self.decompressDims[-1]])
            b = tf.get_variable('aed_b_'+str(i), shape=[self.decompressDims[-1]])
            decodeVariables['aed_W_'+str(i)] = W
            decodeVariables['aed_b_'+str(i)] = b

            if self.dataType == 'binary':
                x_reconst = tf.nn.sigmoid(tf.add(tf.matmul(tempVec,W),b))
                loss = tf.reduce_mean(-tf.reduce_sum(x_input * tf.log(x_reconst + 1e-12) + (1. - x_input) * tf.log(1. - x_reconst + 1e-12), 1), 0)
            else:
                x_reconst = tf.nn.relu(tf.add(tf.matmul(tempVec,W),b))
                loss = tf.reduce_mean((x_input - x_reconst)**2)
            
        return loss, decodeVariables

    def buildGenerator(self, x_input, bn_train):
        tempVec = x_input
        tempDim = self.randomDim
        with tf.variable_scope('generator', regularizer=l2_regularizer(self.l2scale)):
            for i, genDim in enumerate(self.generatorDims[:-1]):
                W = tf.get_variable('W_'+str(i), shape=[tempDim, genDim])
                h = tf.matmul(tempVec,W)
                h2 = batch_norm(h, decay=self.bnDecay, scale=True, is_training=bn_train, updates_collections=None)
                h3 = self.generatorActivation(h2)
                tempVec = h3 + tempVec
                tempDim = genDim
            W = tf.get_variable('W'+str(i), shape=[tempDim, self.generatorDims[-1]])
            h = tf.matmul(tempVec,W)
            h2 = batch_norm(h, decay=self.bnDecay, scale=True, is_training=bn_train, updates_collections=None)

            if self.dataType == 'binary':
                h3 = tf.nn.tanh(h2)
            else:
                h3 = tf.nn.relu(h2)

            output = h3 + tempVec
        return output
    
    def buildGeneratorTest(self, x_input, bn_train):
        tempVec = x_input
        tempDim = self.randomDim
        with tf.variable_scope('generator', regularizer=l2_regularizer(self.l2scale)):
            for i, genDim in enumerate(self.generatorDims[:-1]):
                W = tf.get_variable('W_'+str(i), shape=[tempDim, genDim])
                h = tf.matmul(tempVec,W)
                h2 = batch_norm(h, decay=self.bnDecay, scale=True, is_training=bn_train, updates_collections=None, trainable=False)
                h3 = self.generatorActivation(h2)
                tempVec = h3 + tempVec
                tempDim = genDim
            W = tf.get_variable('W'+str(i), shape=[tempDim, self.generatorDims[-1]])
            h = tf.matmul(tempVec,W)
            h2 = batch_norm(h, decay=self.bnDecay, scale=True, is_training=bn_train, updates_collections=None, trainable=False)

            if self.dataType == 'binary':
                h3 = tf.nn.tanh(h2)
            else:
                h3 = tf.nn.relu(h2)

            output = h3 + tempVec
        return output
    
    def getDiscriminatorResults(self, x_input, keepRate, reuse=False):
        batchSize = tf.shape(x_input)[0]
        inputMean = tf.reshape(tf.tile(tf.reduce_mean(x_input,0), [batchSize]), (batchSize, self.inputDim))
        tempVec = tf.concat(axis = 1, values=[x_input, inputMean])
        tempDim = self.inputDim * 2
        with tf.variable_scope('discriminator', reuse=reuse, regularizer=l2_regularizer(self.l2scale)):
            for i, discDim in enumerate(self.discriminatorDims[:-1]):
                W = tf.get_variable('W_'+str(i), shape=[tempDim, discDim])
                b = tf.get_variable('b_'+str(i), shape=[discDim])
                h = self.discriminatorActivation(tf.add(tf.matmul(tempVec,W),b))
                h = tf.nn.dropout(h, keepRate)
                tempVec = h
                tempDim = discDim
            W = tf.get_variable('W', shape=[tempDim, 1])
            b = tf.get_variable('b', shape=[1])
            y_hat = tf.squeeze(tf.nn.sigmoid(tf.add(tf.matmul(tempVec, W), b)))
        return y_hat
    
    def buildDiscriminator(self, x_real, x_fake, keepRate, decodeVariables, bn_train):
        #Discriminate for real samples
        y_hat_real = self.getDiscriminatorResults(x_real, keepRate, reuse=False)

        #Decompress, then discriminate for real samples
        tempVec = x_fake
        i = 0
        for _ in self.decompressDims[:-1]:
            tempVec = self.aeActivation(tf.add(tf.matmul(tempVec, decodeVariables['aed_W_'+str(i)]), decodeVariables['aed_b_'+str(i)]))
            i += 1

        if self.dataType == 'binary':
            x_decoded = tf.nn.sigmoid(tf.add(tf.matmul(tempVec, decodeVariables['aed_W_'+str(i)]), decodeVariables['aed_b_'+str(i)]))
        else:
            x_decoded = tf.nn.relu(tf.add(tf.matmul(tempVec, decodeVariables['aed_W_'+str(i)]), decodeVariables['aed_b_'+str(i)]))

        y_hat_fake = self.getDiscriminatorResults(x_decoded, keepRate, reuse=True)

        loss_d = -tf.reduce_mean(tf.log(y_hat_real + 1e-12)) - tf.reduce_mean(tf.log(1. - y_hat_fake + 1e-12))
        loss_g = -tf.reduce_mean(tf.log(y_hat_fake + 1e-12))

        return loss_d, loss_g, y_hat_real, y_hat_fake

    def print2file(self, buf, outFile):
        outfd = open(outFile, 'a')
        outfd.write(buf + '\n')
        outfd.close()
    
    def generateData(self,
                     nSamples=100,
                     modelFile='model',
                     batchSize=100,
                     outFile='out'):
        x_dummy = tf.placeholder('float', [None, self.inputDim])
        _, decodeVariables = self.buildAutoencoder(x_dummy)
        x_random = tf.placeholder('float', [None, self.randomDim])
        bn_train = tf.placeholder('bool')
        x_emb = self.buildGeneratorTest(x_random, bn_train)
        tempVec = x_emb
        i = 0
        for _ in self.decompressDims[:-1]:
            tempVec = self.aeActivation(tf.add(tf.matmul(tempVec, decodeVariables['aed_W_'+str(i)]), decodeVariables['aed_b_'+str(i)]))
            i += 1

        if self.dataType == 'binary':
            x_reconst = tf.nn.sigmoid(tf.add(tf.matmul(tempVec, decodeVariables['aed_W_'+str(i)]), decodeVariables['aed_b_'+str(i)]))
        else:
            x_reconst = tf.nn.relu(tf.add(tf.matmul(tempVec, decodeVariables['aed_W_'+str(i)]), decodeVariables['aed_b_'+str(i)]))

        np.random.seed(1234)
        # saver = tf.train.Saver()
        outputVec = []
        burn_in = 1000
        with tf.Session() as sess:
            # saver.restore(sess, modelFile)
            print 'burning in'
            for i in range(burn_in):
                randomX = np.random.normal(size=(batchSize, self.randomDim))
                output = sess.run(x_reconst, feed_dict={x_random:randomX, bn_train:True})

            print 'generating'
            randomX = np.random.normal(size=(self.trainX.shape[0], self.randomDim))
            output = sess.run(x_reconst, feed_dict={x_random:randomX, bn_train:False})
            output = self.c2b(self.trainX, output)
            rv, gv = self.dwp(self.trainX, output, self.validX)
            self.loss_store(self, output, rv, gv)
            outputVec.extend(output)

        # outputMat = np.array(outputVec)
        # np.save(outFile, outputMat)

    def c2b(self, train, generated):
        '''Make the same portion of elements in generated equal to 1 as in train, the rest is set to 0'''

        if np.count_nonzero(generated) <= np.count_nonzero(
                train):  # special case: number of 1 in generated is <= train, all nonzero in train = 1
            np.putmask(generated, generated > 0, 1.0)
            return generated

        p = float(np.count_nonzero(train)) / train.size  # percentage of nonzero elements
        g = sorted(generated.flatten(), reverse=True)
        idx = int(np.around(p * len(g)))
        v = g[idx]  # any value large than this set to 1, o.w. to 0
        # putmask(generated, generated<v, 0.0) # due to the property of putmask, must first set 0 then set 1
        np.putmask(generated, generated >= v, 1.0)
        # print "Nonzero element portion in training data:"
        # print p
        # print "Nonzero element portion in generated data:"
        # print float(count_nonzero(generated))/generated.size
        return generated

    def split(self, matrix, col):
        '''split matrix into feature and target (col th column of matrix), matrix \in R^{N*D}, f_r \in R^{N*(D-1)} , t_r \in R^{N*1}'''
        t_r = matrix[:, col]  # shape: (len(t_r),)
        f_r = np.delete(matrix, col, 1)
        return f_r, t_r

    def dwp(self, r, g, te, C=1.0):
        '''Dimension-wise prediction, r for real, g for generated, t for test, all without separated feature and target, all are numpy array'''
        rv = []
        gv = []
        for i in range(len(r[0])):
            print i

            f_r, t_r = self.split(r, i)  # separate feature and target
            f_g, t_g = self.split(g, i)
            f_te, t_te = self.split(te, i)  # these 6 are all numpy array
            t_g[t_g < 1] = 0  # transfer non 1 to 0 (c to b)
            if (np.unique(t_r).size == 1) or (np.unique(
                    t_g).size == 1):  # if only those coordinates correspondent to top codes are kept, no coordinate should be skipped, if those patients that doesn't contain top ICD9 codes were removed, more coordinates will be skipped
                print "skip this coordinate"
                continue

            model_r = linear_model.LogisticRegression(
                C=C)  # logistic regression, if labels are all 0, this will cause: ValueError: This solver needs samples of at least 2 classes in the data, but the data contains only one class: 0
            model_r.fit(f_r, t_r)
            label_r = model_r.predict(f_te)
            model_g = linear_model.LogisticRegression(C=C)
            model_g.fit(f_g, t_g)
            label_g = model_r.predict(f_te)
            # print label_r
            # print mean(model_r.coef_), count_nonzero(model_r.coef_), mean(model_g.coef_), count_nonzero(model_g.coef_) # statistics of classifiers
            # rv.append(match(label_r, t_te)/(len(t_te)+10**(-10))) # simply match
            # gv.append(match(label_g, t_te)/(len(t_te)+10**(-10)))
            rv.append(f1_score(t_te, label_r))  # F1 score
            gv.append(f1_score(t_te, label_g))

        return rv, gv

    def loss_store(self, x_gene, rv, gv):
        '''store everything new added'''
        num_bins = 20
        plt.hist(gv, num_bins, facecolor='red', alpha=0.5)
        plt.savefig('./result/genefinalfig/Histogram.jpg')
        plt.close() # clears the entire current figure with all its axes
        with open('./result/genefinalfig/real.pickle', 'wb') as fp:
            pickle.dump(rv, fp)
        with open('./result/genefinalfig/generated.pickle', 'wb') as fp:
            pickle.dump(gv, fp)
        with open('./result/genefinalfig/x_gene.pickle', 'wb') as fp: # store generated EHR and figures
            pickle.dump(x_gene, fp)
        plt.close()
        plt.scatter(rv, gv)
        plt.title('Scatter plot of dimension-wise MSE')
        plt.xlabel('Real')
        plt.ylabel('Generated')
        plt.savefig('./result/genefinalfig/dwp.jpg')

    def calculateDiscAuc(self, preds_real, preds_fake):
        preds = np.concatenate([preds_real, preds_fake], axis=0)
        labels = np.concatenate([np.ones((len(preds_real))), np.zeros((len(preds_fake)))], axis=0)
        auc = roc_auc_score(labels, preds)
        return auc
    
    def calculateDiscAccuracy(self, preds_real, preds_fake):
        total = len(preds_real) + len(preds_fake)
        hit = 0
        for pred in preds_real: 
            if pred > 0.5: hit += 1
        for pred in preds_fake: 
            if pred < 0.5: hit += 1
        acc = float(hit) / float(total)
        return acc

    def train(self,
              dataPath='data',
              modelPath='',
              outPath='out',
              nEpochs=2,
              discriminatorTrainPeriod=2,
              generatorTrainPeriod=1,
              pretrainBatchSize=100,
              batchSize=1000,
              pretrainEpochs=2,
              saveMaxKeep=0):
        x_raw = tf.placeholder('float', [None, self.inputDim])
        x_random= tf.placeholder('float', [None, self.randomDim])
        keep_prob = tf.placeholder('float')
        bn_train = tf.placeholder('bool')

        loss_ae, decodeVariables = self.buildAutoencoder(x_raw)
        x_fake = self.buildGenerator(x_random, bn_train)
        loss_d, loss_g, y_hat_real, y_hat_fake = self.buildDiscriminator(x_raw, x_fake, keep_prob, decodeVariables, bn_train)
        # trainX, validX = self.loadData(dataPath)

        t_vars = tf.trainable_variables()
        ae_vars = [var for var in t_vars if 'autoencoder' in var.name]
        d_vars = [var for var in t_vars if 'discriminator' in var.name]
        g_vars = [var for var in t_vars if 'generator' in var.name]

        all_regs = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)

        optimize_ae = tf.train.AdamOptimizer().minimize(loss_ae + sum(all_regs), var_list=ae_vars)
        optimize_d = tf.train.AdamOptimizer().minimize(loss_d + sum(all_regs), var_list=d_vars)
        optimize_g = tf.train.AdamOptimizer().minimize(loss_g + sum(all_regs), var_list=g_vars+decodeVariables.values())

        initOp = tf.global_variables_initializer()

        nBatches = int(np.ceil(float(self.trainX.shape[0]) / float(batchSize)))
        # saver = tf.train.Saver(max_to_keep=saveMaxKeep)
        logFile = outPath + '.log'

        with tf.Session() as sess:
            if modelPath == '': sess.run(initOp)
            # else: saver.restore(sess, modelPath)
            nTrainBatches = int(np.ceil(float(self.trainX.shape[0])) / float(pretrainBatchSize))
            nValidBatches = int(np.ceil(float(self.validX.shape[0])) / float(pretrainBatchSize))

            if modelPath== '':
                for epoch in range(pretrainEpochs):
                    idx = np.random.permutation(self.trainX.shape[0])
                    trainLossVec = []
                    for i in range(nTrainBatches):
                        batchX = self.trainX[idx[i*pretrainBatchSize:(i+1)*pretrainBatchSize]]
                        _, loss = sess.run([optimize_ae, loss_ae], feed_dict={x_raw:batchX})
                        trainLossVec.append(loss)
                    idx = np.random.permutation(self.validX.shape[0])
                    validLossVec = []
                    for i in range(nValidBatches):
                        batchX = self.validX[idx[i*pretrainBatchSize:(i+1)*pretrainBatchSize]]
                        loss = sess.run(loss_ae, feed_dict={x_raw:batchX})
                        validLossVec.append(loss)
                    validReverseLoss = 0.
                    buf = 'Pretrain_Epoch:%d, trainLoss:%f, validLoss:%f, validReverseLoss:%f' % (epoch, np.mean(trainLossVec), np.mean(validLossVec), validReverseLoss)
                    print buf
                    self.print2file(buf, logFile)

            idx = np.arange(self.trainX.shape[0])
            for epoch in range(nEpochs):
                d_loss_vec= []
                g_loss_vec = []
                for i in range(nBatches):
                    for _ in range(discriminatorTrainPeriod):
                        batchIdx = np.random.choice(idx, size=batchSize, replace=False)
                        batchX = self.trainX[batchIdx]
                        randomX = np.random.normal(size=(batchSize, self.randomDim))
                        _, discLoss = sess.run([optimize_d, loss_d], feed_dict={x_raw:batchX, x_random:randomX, keep_prob:1.0, bn_train:False})
                        d_loss_vec.append(discLoss)
                    for _ in range(generatorTrainPeriod):
                        randomX = np.random.normal(size=(batchSize, self.randomDim))
                        _, generatorLoss = sess.run([optimize_g, loss_g], feed_dict={x_raw:batchX, x_random:randomX, keep_prob:1.0, bn_train:True})
                        g_loss_vec.append(generatorLoss)

                idx = np.arange(len(self.validX))
                nValidBatches = int(np.ceil(float(len(self.validX)) / float(batchSize)))
                validAccVec = []
                validAucVec = []
                for i in range(nBatches):
                    batchIdx = np.random.choice(idx, size=batchSize, replace=False)
                    batchX = self.validX[batchIdx]
                    randomX = np.random.normal(size=(batchSize, self.randomDim))
                    preds_real, preds_fake, = sess.run([y_hat_real, y_hat_fake], feed_dict={x_raw:batchX, x_random:randomX, keep_prob:1.0, bn_train:False})
                    validAcc = self.calculateDiscAccuracy(preds_real, preds_fake)
                    validAuc = self.calculateDiscAuc(preds_real, preds_fake)
                    validAccVec.append(validAcc)
                    validAucVec.append(validAuc)
                buf = 'Epoch:%d, d_loss:%f, g_loss:%f, accuracy:%f, AUC:%f' % (epoch, np.mean(d_loss_vec), np.mean(g_loss_vec), np.mean(validAccVec), np.mean(validAucVec))
                print buf
                self.print2file(buf, logFile)
                # savePath = saver.save(sess, outPath, global_step=epoch)
        # print  savePath


def parse_arguments(parser):
    parser.add_argument('--embed_size', type=int, default=128, help='The dimension size of the embedding, which will be generated by the generator. (default value: 128)')
    parser.add_argument('--noise_size', type=int, default=128, help='The dimension size of the random noise, on which the generator is conditioned. (default value: 128)')
    parser.add_argument('--generator_size', type=tuple, default=(128, 128), help='The dimension size of the generator. Note that another layer of size "--embed_size" is always added. (default value: (128, 128))')
    parser.add_argument('--discriminator_size', type=tuple, default=(256, 128, 1), help='The dimension size of the discriminator. (default value: (256, 128, 1))')
    parser.add_argument('--compressor_size', type=tuple, default=(), help='The dimension size of the encoder of the autoencoder. Note that another layer of size "--embed_size" is always added. Therefore this can be a blank tuple. (default value: ())')
    parser.add_argument('--decompressor_size', type=tuple, default=(), help='The dimension size of the decoder of the autoencoder. Note that another layer, whose size is equal to the dimension of the <patient_matrix>, is always added. Therefore this can be a blank tuple. (default value: ())')
    parser.add_argument('--data_type', type=str, default='binary', choices=['binary', 'count'], help='The input data type. The <patient matrix> could either contain binary values or count values. (default value: "binary")')
    parser.add_argument('--batchnorm_decay', type=float, default=0.99, help='Decay value for the moving average used in Batch Normalization. (default value: 0.99)')
    parser.add_argument('--L2', type=float, default=0.001, help='L2 regularization coefficient for all weights. (default value: 0.001)')

    parser.add_argument('data_file', type=str, metavar='<patient_matrix>', help='The path to the numpy matrix containing aggregated patient records.')
    parser.add_argument('out_file', type=str, metavar='<out_file>', help='The path to the output models.')
    parser.add_argument('--model_file', type=str, metavar='<model_file>', default='', help='The path to the model file, in case you want to continue training. (default value: '')')
    parser.add_argument('--n_pretrain_epoch', type=int, default=2, help='The number of epochs to pre-train the autoencoder. (default value: 100)')
    parser.add_argument('--n_epoch', type=int, default=2, help='The number of epochs to train medGAN. (default value: 1000)')
    parser.add_argument('--n_discriminator_update', type=int, default=2, help='The number of times to update the discriminator per epoch. (default value: 2)')
    parser.add_argument('--n_generator_update', type=int, default=1, help='The number of times to update the generator per epoch. (default value: 1)')
    parser.add_argument('--pretrain_batch_size', type=int, default=100, help='The size of a single mini-batch for pre-training the autoencoder. (default value: 100)')
    parser.add_argument('--batch_size', type=int, default=1000, help='The size of a single mini-batch for training medGAN. (default value: 1000)')
    parser.add_argument('--save_max_keep', type=int, default=0, help='The number of models to keep. Setting this to 0 will save models for every epoch. (default value: 0)')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    args = parse_arguments(parser)

    data = np.load(args.data_file)
    inputDim = data.shape[1]

    mg = Medgan(dataType=args.data_type,
                inputDim=inputDim,
                embeddingDim=args.embed_size,
                randomDim=args.noise_size,
                generatorDims=args.generator_size,
                discriminatorDims=args.discriminator_size,
                compressDims=args.compressor_size,
                decompressDims=args.decompressor_size,
                bnDecay=args.batchnorm_decay,
                l2scale=args.L2)

    mg.train(dataPath=args.data_file,
             modelPath=args.model_file,
             outPath=args.out_file,
             pretrainEpochs=args.n_pretrain_epoch,
             nEpochs=args.n_epoch,
             discriminatorTrainPeriod=args.n_discriminator_update,
             generatorTrainPeriod=args.n_generator_update,
             pretrainBatchSize=args.pretrain_batch_size,
             batchSize=args.batch_size,
             saveMaxKeep=args.save_max_keep)

    # To generate synthetic data using a trained model:
    # Comment the train function above and un-comment generateData function below.
    # You must specify "--model_file" and "<out_file>" to generate synthetic data.
    mg.generateData(nSamples=10000,
                    modelFile=args.model_file,
                    batchSize=args.batch_size,
                    outFile=args.out_file)