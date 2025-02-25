from load_data import load_adult
from sklearn import svm
from sklearn.metrics import accuracy_score
import numpy as np
from measures import equalized_odds_measure_TP
from sklearn.model_selection import GridSearchCV
from collections import namedtuple
import sys
import time


class Linear_FERM:
    # The linear FERM algorithm
    def __init__(self, dataset, model, sensible_feature, prior=False, pi=1):
        self.dataset = dataset
        self.values_of_sensible_feature = list(set(sensible_feature))
        self.list_of_sensible_feature_train = sensible_feature
        self.val0 = np.min(self.values_of_sensible_feature)
        self.val1 = np.max(self.values_of_sensible_feature)
        self.model = model
        self.u = None
        self.max_i = None
        self.prior = prior
        self.pi = pi  # the ratio between two groups

    def new_representation(self, examples):
        if self.u is None:
            sys.exit('Model not trained yet!')
            return 0

        new_examples = np.array([ex - self.u * (ex[self.max_i] / self.u[self.max_i]) for ex in examples])
        new_examples = np.delete(new_examples, self.max_i, 1)
        return new_examples

    def predict(self, examples):
        new_examples = self.new_representation(examples)
        prediction = self.model.predict(new_examples)
        return prediction

    def fit(self):
        # Evaluation of the empirical averages among the groups
        tmp = [ex for idx, ex in enumerate(self.dataset.data)
               if self.dataset.target[idx] == 1 and self.list_of_sensible_feature_train[idx] == self.val1]
        average_A_1 = np.mean(tmp, 0)
        tmp = [ex for idx, ex in enumerate(self.dataset.data)
               if self.dataset.target[idx] == 1 and self.list_of_sensible_feature_train[idx] == self.val0]
        average_not_A_1 = np.mean(tmp, 0)

        # Evaluation of the vector u (difference among the two averages)
        if self.prior: # we have some prior knowledge that the probability of female getting AD is twice that of male
            self.u = -(average_A_1 - self.pi * average_not_A_1)
        else:
            self.u = -(average_A_1 - average_not_A_1)
        self.max_i = np.argmax(self.u)

        # Application of the new representation
        newdata = np.array([ex - self.u * (ex[self.max_i] / self.u[self.max_i]) for ex in self.dataset.data])
        newdata = np.delete(newdata, self.max_i, 1)
        self.dataset = namedtuple('_', 'data, target')(newdata, self.dataset.target)

        # Fitting the linear model by using the new data
        if self.model:
            self.model.fit(self.dataset.data, self.dataset.target)


class Linear_PFERM(Linear_FERM):
    def __init__(self, dataset, model, sensible_feature, prior=False, pi=1):
        self.dataset = dataset
        self.values_of_sensible_feature = np.unique(sensible_feature)  # sorted feature values small to large
        self.list_of_sensible_feature_train = sensible_feature
        self.model = model
        self.u = None
        self.max_i = None
        self.prior = prior
        self.pi = pi  # the ratio between two groups


    def fit(self):

        # Evaluation of the vector u (difference among the two averages)
        self.group_list = []  # the list of mean value of each group with positive class, such as male and female or different races
        for val in self.values_of_sensible_feature:
            self.group_list.append(np.mean(
                [ex for idx, ex in enumerate(self.dataset.data)
                 if self.dataset.target[idx] == 1 and sensible_feature[idx] == val], 0))
        # calculate all the u (i.e., u_1 - u_k)
        self.u_list = []
        first_group_mean = self.group_list[0]
        for idx, group_mean in enumerate(self.group_list):
            if idx == 0:
                continue
            self.u_list.append(first_group_mean - group_mean)

        # if self.prior:  # we have some prior knowledge that the probability of female getting AD is twice that of male
        #     self.u = -(average_A_1 - self.pi * average_not_A_1)
        # else:
        #     self.u = -(average_A_1 - average_not_A_1)
        # self.max_i = np.argmax(self.u)

        # Application of the new representation
        num_u = len(self.u_list)  # the number of u is g-1 where g is the number of all the groups
        # U = np.empty(num_u, num_u)  # U is the matrix of all u
        U = []
        # Uk_list is the list of all the U_k
        # U_k is the matrix of all u where the kth element of each u (each row) is replaced by u_k
        Uk_list = [[]] * num_u
        for u in self.u_list:
            U.append(u[:num_u])
        U = np.array(U)

        for idx, u in enumerate(self.u_list):
            temp_u = u
            temp_u[idx] = u[idx]
            Uk_list[idx].append(temp_u[:num_u])


        newdata = np.array([ex - self.u * (ex[self.max_i] / self.u[self.max_i]) for ex in self.dataset.data])
        newdata = np.delete(newdata, self.max_i, 1)
        self.dataset = namedtuple('_', 'data, target')(newdata, self.dataset.target)

        # Fitting the linear model by using the new data
        if self.model:
            self.model.fit(self.dataset.data, self.dataset.target)


if __name__ == "__main__":
    start_time = time.perf_counter()
    print('start time is: ', start_time)

    # Load Adult dataset
    # dataset_train, dataset_test = load_adult(smaller=False)
    X_train, X_test, y_train, y_test, sensible_feature, pi = load_adult(seed=0, smaller=True)
    dataset_train = namedtuple('_', 'data, target')(X_train, y_train)
    dataset_test = namedtuple('_', 'data, target')(X_test, y_test)
    # sensible_feature = 9  # GENDER
    sensible_feature_values = sorted(list(set(dataset_train.data[:, sensible_feature])))
    print('Different values of the sensible feature', sensible_feature, ':', sensible_feature_values)
    ntrain = len(dataset_train.target)

    # Standard SVM -  Train an SVM using the training set
    print('Grid search...')
    param_grid = [{'C': [0.01, 0.1, 1.0], 'kernel': ['linear']}]
    svc = svm.SVC()
    clf = GridSearchCV(svc, param_grid, n_jobs=1)
    clf.fit(dataset_train.data, dataset_train.target)
    print('Best Estimator:', clf.best_estimator_)

    # Accuracy and Fairness
    pred = clf.predict(dataset_test.data)
    pred_train = clf.predict(dataset_train.data)
    print('Accuracy test:', accuracy_score(dataset_test.target, pred))
    print('Accuracy train:', accuracy_score(dataset_train.target, pred_train))
    # Fairness measure
    EO_train = equalized_odds_measure_TP(dataset_train, clf, [sensible_feature], ylabel=1)
    EO_test = equalized_odds_measure_TP(dataset_test, clf, [sensible_feature], ylabel=1)
    print('DEO test:', np.abs(2*EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(2*EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    # Linear FERM
    list_of_sensible_feature_test = dataset_test.data[:, sensible_feature]
    print('\n\n\nGrid search for our method...')
    svc = svm.SVC()
    clf = GridSearchCV(svc, param_grid, n_jobs=1)
    algorithm = Linear_FERM(dataset_train, clf, dataset_train.data[:, sensible_feature])
    algorithm.fit()
    print('Best Fair Estimator::', algorithm.model.best_estimator_)

    # Accuracy and Fairness
    pred = algorithm.predict(dataset_test.data)
    pred_train = algorithm.predict(dataset_train.data)
    print('Accuracy test fair:', accuracy_score(dataset_test.target, pred))
    print('Accuracy train fair:', accuracy_score(dataset_train.target, pred_train))
    # Fairness measure
    EO_train = equalized_odds_measure_TP(dataset_train, algorithm, [sensible_feature], ylabel=1)
    EO_test = equalized_odds_measure_TP(dataset_test, algorithm, [sensible_feature], ylabel=1)
    print('DEO test:', np.abs(EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    e = int(time.perf_counter() - start_time)
    print('Elapsed Time: {:02d}:{:02d}:{:02d}'.format(e // 3600, (e % 3600 // 60), e % 60))