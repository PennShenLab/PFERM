from load_data import load_adult, load_toy_three_group, load_toy_new
from sklearn import svm
from sklearn.metrics import accuracy_score
from measures import equalized_odds_measure_TP
from sklearn.model_selection import GridSearchCV
from cvxopt import matrix
import numpy as np
from numpy import linalg
import cvxopt
import cvxopt.solvers
from sklearn.base import BaseEstimator
from sklearn.metrics.pairwise import rbf_kernel
import time
from collections import namedtuple


# Definition of different kernels
def linear_kernel(x1, x2):
    return np.dot(x1, np.transpose(x2))

def gaussian_kernel(x, y, gamma=0.1):
    return np.exp(-gamma * (linalg.norm(x - y)**2))


class FERM(BaseEstimator):
    # FERM algorithm
    def __init__(self, kernel='rbf', C=1.0, sensible_feature=None,
                 gamma=1.0, prior=False, pi=1, constraint='EO', lamda=0.5):
        self.kernel = kernel
        self.C = C
        self.fairness = False if sensible_feature is None else True
        self.sensible_feature = sensible_feature
        self.gamma = gamma
        self.w = None
        self.prior = prior  # added by hobo, whether to use prior knowledge
        self.pi = pi  # pi as the prior knowledge, is the ratio between two groups
        self.constraint = constraint  # whether to use EO or DP as constraint
        self.lamda = lamda

    def fit(self, X, y):
        if self.kernel == 'rbf':
            self.fkernel = lambda x, y: rbf_kernel(x, y, self.gamma)
        elif self.kernel == 'linear':
            self.fkernel = linear_kernel
        else:
            self.fkernel = linear_kernel

        if self.fairness:
            self.values_of_sensible_feature = list(set(self.sensible_feature))
            self.list_of_sensible_feature_train = self.sensible_feature
            self.val0 = np.min(self.values_of_sensible_feature)
            self.val1 = np.max(self.values_of_sensible_feature)
            self.set_A1 = [idx for idx, ex in enumerate(X) if y[idx] == 1
                           and self.sensible_feature[idx] == self.val1]
            self.set_not_A1 = [idx for idx, ex in enumerate(X) if y[idx] == 1
                               and self.sensible_feature[idx] == self.val0]
            # print('self.val0:', self.val0)
            # print('self.val1:', self.val1)
            # print('(y, self.sensible_feature):')
            # for el in zip(y, self.sensible_feature):
            #     print(el)
            self.set_1 = [idx for idx, ex in enumerate(X) if y[idx] == 1]
            self.n_A1 = len(self.set_A1)
            self.n_not_A1 = len(self.set_not_A1)
            self.n_1 = len(self.set_1)

        n_samples, n_features = X.shape

        # Gram matrix
        K = self.fkernel(X, X)

        P = cvxopt.matrix(np.outer(y, y) * K)
        q = cvxopt.matrix(np.ones(n_samples) * -1)
        # print(y)
        A = cvxopt.matrix(y.astype(np.double), (1, n_samples), 'd')
        b = cvxopt.matrix(0.0)

        if self.C is None:  # \alpha should be larger than 0
            G = cvxopt.matrix(np.diag(np.ones(n_samples) * -1))
            h = cvxopt.matrix(np.zeros(n_samples))
        else:  # \alpha should be between 0 and C
            tmp1 = np.diag(np.ones(n_samples) * -1)
            tmp2 = np.identity(n_samples)
            G = cvxopt.matrix(np.vstack((tmp1, tmp2)))
            tmp1 = np.zeros(n_samples)
            tmp2 = np.ones(n_samples) * self.C
            h = cvxopt.matrix(np.hstack((tmp1, tmp2)))

        # Stack the fairness constraint
        if self.fairness:
            if self.prior: # prior knowledge that the probability of female getting AD is twice that of male
                if isinstance(self.pi, list):
                    # tau = [(np.sum(K[self.set_A1, idx]) / self.n_A1) -
                    #        self.pi[0] * (np.sum(K[self.set_not_A1, idx]) / self.n_not_A1)
                    #        for idx in range(len(y))]

                    # we do the combination between \pi and 1, (1-\lambda) * \pi + \lambda
                    tau = [(np.sum(K[self.set_A1, idx]) / self.n_A1) -
                           ((1 - self.lamda) * self.pi[0] + self.lamda) * (np.sum(K[self.set_not_A1, idx]) / self.n_not_A1)
                           for idx in range(len(y))]
                else:
                    # tau = [(np.sum(K[self.set_A1, idx]) / self.n_A1) -
                    #        self.pi * (np.sum(K[self.set_not_A1, idx]) / self.n_not_A1)
                    #        for idx in range(len(y))]

                    # we do the combination between \pi and 1, (1-\lambda) * \pi + \lambda
                    tau = [(np.sum(K[self.set_A1, idx]) / self.n_A1) -
                           ((1 - self.lamda) * self.pi + self.lamda) * (np.sum(K[self.set_not_A1, idx]) / self.n_not_A1)
                           for idx in range(len(y))]
            else:
                tau = [(np.sum(K[self.set_A1, idx]) / self.n_A1) -
                       (np.sum(K[self.set_not_A1, idx]) / self.n_not_A1)
                       for idx in range(len(y))]
            # print('self.n_A1:', self.n_A1)
            # print('self.n_not_A1:', self.n_not_A1)
            # print('tau:', tau)
            fairness_line = matrix(y * tau, (1, n_samples), 'd')
            A = cvxopt.matrix(np.vstack([A, fairness_line]))
            b = cvxopt.matrix([0.0, 0.0])

        # solve QP problem
        cvxopt.solvers.options['show_progress'] = False
        # print('A:', A)
        # print('Rank(A):', np.linalg.matrix_rank(A))
        # print('Rank([P; A; G])', np.linalg.matrix_rank(np.vstack([P, A, G])))
        solution = cvxopt.solvers.qp(P, q, G, h, A, b)

        # Lagrange multipliers
        a = np.ravel(solution['x'])

        # Support vectors have non zero lagrange multipliers
        sv = a > 1e-7
        ind = np.arange(len(a))[sv]
        self.a = a[sv]
        self.sv = X[sv]
        self.sv_y = y[sv]
        # print("%d support vectors out of %d points" % (len(self.a), n_samples))

        # Intercept
        self.b = 0
        for n in range(len(self.a)):
            self.b += self.sv_y[n]
            self.b -= np.sum(self.a * self.sv_y * K[ind[n], sv])
        self.b /= len(self.a)

        # Weight vector
        if self.kernel == linear_kernel:
            self.w = np.zeros(n_features)
            for n in range(len(self.a)):
                self.w += self.a[n] * self.sv_y[n] * self.sv[n]
        else:
            self.w = None

    def project(self, X):
        if self.w is not None:
            return np.dot(X, self.w) + self.b
        else:
            XSV = self.fkernel(X, self.sv)
            a_sv_y = np.multiply(self.a, self.sv_y)
            y_predict = [np.sum(np.multiply(np.multiply(self.a, self.sv_y), XSV[i, :])) for i in range(len(X))]

            return y_predict + self.b

    def decision_function(self, X):
        return self.project(X)

    def predict(self, X):
        return np.sign(self.project(X))

    def score(self, X_test, y_test):
        predict = self.predict(X_test)
        acc = accuracy_score(y_test, predict)
        return acc


class PFERM(FERM):
    # def __init__(self, kernel='rbf', C=1.0, sensible_feature=None, gamma=1.0, prior=False, pi=1):
    #     super().__init__(kernel=kernel, C=C, sensible_feature=sensible_feature, gamma=gamma, prior=prior, pi=pi)

    def fit(self, X, y):
        if self.kernel == 'rbf':
            self.fkernel = lambda x, y: rbf_kernel(x, y, self.gamma)
        elif self.kernel == 'linear':
            self.fkernel = linear_kernel
        else:
            self.fkernel = linear_kernel

        if self.fairness:
            self.values_of_sensible_feature = np.unique(self.sensible_feature) # sorted feature values small to large

            self.group_idx_list = []  # the index list of each group with positive class, such as male and female or different races

            if self.constraint == 'EO':  # equalized odds as constraint
                for val in self.values_of_sensible_feature:
                    self.group_idx_list.append(
                        [idx for idx, ex in enumerate(X)
                         if y[idx] == 1 and self.sensible_feature[idx] == val])
            else:  # demographic parity as constraint
                for val in self.values_of_sensible_feature:
                    self.group_idx_list.append(
                        [idx for idx, ex in enumerate(X)
                         if self.sensible_feature[idx] == val])

            self.n_list = [len(idx) for idx in self.group_idx_list]  # number of positive instances in each group

            # print('self.val0:', self.val0)
            # print('self.val1:', self.val1)
            # print('(y, self.sensible_feature):')
            # for el in zip(y, self.sensible_feature):
            #     print(el)
            # self.set_1 = [idx for idx, ex in enumerate(X) if y[idx] == 1]  # index of positive instances
            # self.n_1 = len(self.set_1)  # number of positive instances

        n_samples, n_features = X.shape

        # Gram matrix
        K = self.fkernel(X, X)

        P = cvxopt.matrix(np.outer(y, y) * K)
        q = cvxopt.matrix(np.ones(n_samples) * -1)
        # print(y)
        A = cvxopt.matrix(y.astype(np.double), (1, n_samples), 'd')
        b = cvxopt.matrix(0.0)

        if self.C is None:  # \alpha should be larger than 0
            G = cvxopt.matrix(np.diag(np.ones(n_samples) * -1))
            h = cvxopt.matrix(np.zeros(n_samples))
        else:  # \alpha should be between 0 and C
            tmp1 = np.diag(np.ones(n_samples) * -1)
            tmp2 = np.identity(n_samples)
            G = cvxopt.matrix(np.vstack((tmp1, tmp2)))
            tmp1 = np.zeros(n_samples)
            tmp2 = np.ones(n_samples) * self.C
            h = cvxopt.matrix(np.hstack((tmp1, tmp2)))

        # Stack the fairness constraint
        if self.fairness:
            if self.prior: # prior knowledge that the probability of female getting AD is twice that of male
                self.tau_list = []
                first_group_idx = self.group_idx_list[0]
                first_n = self.n_list[0]
                for i, (group_idx, current_n) in enumerate(zip(self.group_idx_list, self.n_list)):
                    if i == 0:
                        continue
                    if isinstance(self.pi, list):
                        self.tau_list.append(
                            [(np.sum(K[group_idx, idx]) / current_n) -
                             ((1 - self.lamda) * self.pi[i-1] + self.lamda) * (np.sum(K[first_group_idx, idx]) / first_n)
                             for idx in range(len(y))])
                    else:
                        self.tau_list.append(
                            [(np.sum(K[group_idx, idx]) / current_n) -
                             ((1 - self.lamda) * self.pi + self.lamda) * (np.sum(K[first_group_idx, idx]) / first_n)
                             for idx in range(len(y))])

            else:
                self.tau_list = []
                first_group_idx = self.group_idx_list[0]
                first_n = self.n_list[0]
                for i, (group_idx, current_n) in enumerate(zip(self.group_idx_list, self.n_list)):
                    if i == 0:
                        continue
                    self.tau_list.append(
                        [(np.sum(K[group_idx, idx]) / current_n) -
                         (np.sum(K[first_group_idx, idx]) / first_n)
                           for idx in range(len(y))])
            # print('self.n_A1:', self.n_A1)
            # print('self.n_not_A1:', self.n_not_A1)
            # print('tau:', self.tau_list)
            # print('A:', A.size, np.sum(A[0,:]))
            A_list = [A]
            for tau in self.tau_list:
                A_list.append(matrix(y * tau, (1, n_samples), 'd'))
            A = cvxopt.matrix(np.vstack(A_list))
            b = cvxopt.matrix([0.0] * len(A_list))

            # print('A tau 1:', A.size, np.sum(A[1, :]))
            # print('A tau 2:', A.size, np.sum(A[2, :]))

        # solve QP problem
        cvxopt.solvers.options['show_progress'] = False
        # print('A:', A)
        # print('Rank(A):', np.linalg.matrix_rank(A))
        # print('Rank([P; A; G])', np.linalg.matrix_rank(np.vstack([P, A, G])))
        solution = cvxopt.solvers.qp(P, q, G, h, A, b)

        # Lagrange multipliers
        a = np.ravel(solution['x'])

        # Support vectors have non zero lagrange multipliers
        sv = a > 1e-7
        ind = np.arange(len(a))[sv]
        self.a = a[sv]
        self.sv = X[sv]
        self.sv_y = y[sv]
        # print("%d support vectors out of %d points" % (len(self.a), n_samples))

        # Intercept
        self.b = 0
        for n in range(len(self.a)):
            self.b += self.sv_y[n]
            self.b -= np.sum(self.a * self.sv_y * K[ind[n], sv])
        self.b /= len(self.a)

        # Weight vector
        if self.kernel == linear_kernel:
            self.w = np.zeros(n_features)
            for n in range(len(self.a)):
                self.w += self.a[n] * self.sv_y[n] * self.sv[n]
        else:
            self.w = None


if __name__ == "__main__":

    start_time = time.perf_counter()
    print('start time is: ', start_time)

    # Load Adult dataset (a smaller version!)
    # X_train, X_test, y_train, y_test, sensible_feature, pi = load_adult(seed=0, smaller=True)
    X_train, X_test, y_train, y_test, sensible_feature, pi = load_toy_three_group(seed=0)
    # X_train, X_test, y_train, y_test, sensible_feature, pi = load_toy_new(seed=0)
    dataset_train = namedtuple('_', 'data, target')(X_train, y_train)
    dataset_test = namedtuple('_', 'data, target')(X_test, y_test)
    # sensible_feature = 9  # GENDER
    sensible_feature_values = sorted(list(set(dataset_train.data[:, sensible_feature])))
    print('Different values of the sensible feature', sensible_feature, ':', sensible_feature_values)
    ntrain = len(dataset_train.target)

    # Standard SVM - Train an SVM using the training set
    # print('Grid search for SVM...')
    grid_search_complete = 1
    if grid_search_complete:
        param_grid = [{'C': [0.1, 1, 10.0],
                       'gamma': [0.1, 0.01],
                       'kernel': ['rbf']}
                      ]
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
    print('DEO test:', np.abs(EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    #  FERM algorithm
    print('\n\nGrid search for original FERM...')
    algorithm = FERM(sensible_feature=dataset_train.data[:, sensible_feature])
    clf = GridSearchCV(algorithm, param_grid, n_jobs=1)
    clf.fit(dataset_train.data, dataset_train.target)
    # print('Best Fair Estimator:', clf.best_estimator_)
    print('Best Estimator: FERM(C={}, gamma={})'.
          format(clf.best_estimator_.C, clf.best_estimator_.gamma))

    # Accuracy and Fairness
    y_predict = clf.predict(dataset_test.data)
    pred = clf.predict(dataset_test.data)
    pred_train = clf.predict(dataset_train.data)
    print('Accuracy test:', accuracy_score(dataset_test.target, pred))
    print('Accuracy train:', accuracy_score(dataset_train.target, pred_train))
    # Fairness measure
    EO_train = equalized_odds_measure_TP(dataset_train, clf, [sensible_feature], ylabel=1)
    EO_test = equalized_odds_measure_TP(dataset_test, clf, [sensible_feature], ylabel=1)
    print('DEO test:', np.abs(EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    #  FERM algorithm
    print('\n\nGrid search for new FERM...')
    algorithm = PFERM(sensible_feature=dataset_train.data[:, sensible_feature])
    clf = GridSearchCV(algorithm, param_grid, n_jobs=1)
    clf.fit(dataset_train.data, dataset_train.target)
    # print('Best Fair Estimator:', clf.best_estimator_)
    print('Best Estimator: FERM(C={}, gamma={})'.
          format(clf.best_estimator_.C, clf.best_estimator_.gamma))

    # Accuracy and Fairness
    y_predict = clf.predict(dataset_test.data)
    pred = clf.predict(dataset_test.data)
    pred_train = clf.predict(dataset_train.data)
    print('Accuracy test:', accuracy_score(dataset_test.target, pred))
    print('Accuracy train:', accuracy_score(dataset_train.target, pred_train))
    # Fairness measure
    EO_train = equalized_odds_measure_TP(dataset_train, clf, [sensible_feature], ylabel=1)
    EO_test = equalized_odds_measure_TP(dataset_test, clf, [sensible_feature], ylabel=1)
    print('DEO test:', np.abs(EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    #  PFERM algorithm
    print('\n\nGrid search for original PFERM...')
    algorithm = FERM(sensible_feature=dataset_train.data[:, sensible_feature], prior=True, pi=pi)
    clf = GridSearchCV(algorithm, param_grid, n_jobs=1)
    clf.fit(dataset_train.data, dataset_train.target)
    # print('Best Fair Estimator:', clf.best_estimator_)
    print('Best Estimator: PFERM(C={}, gamma={})'.
          format(clf.best_estimator_.C, clf.best_estimator_.gamma))

    # Accuracy and Fairness
    y_predict = clf.predict(dataset_test.data)
    pred = clf.predict(dataset_test.data)
    pred_train = clf.predict(dataset_train.data)
    print('Accuracy test:', accuracy_score(dataset_test.target, pred))
    print('Accuracy train:', accuracy_score(dataset_train.target, pred_train))
    # Fairness measure
    EO_train = equalized_odds_measure_TP(dataset_train, clf, [sensible_feature], ylabel=1)
    EO_test = equalized_odds_measure_TP(dataset_test, clf, [sensible_feature], ylabel=1)
    print('DEO test:', np.abs(EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    #  PFERM algorithm
    print('\n\nGrid search for new PFERM...')
    algorithm = PFERM(sensible_feature=dataset_train.data[:, sensible_feature], prior=True, pi=pi)
    clf = GridSearchCV(algorithm, param_grid, n_jobs=1)
    clf.fit(dataset_train.data, dataset_train.target)
    # print('Best Fair Estimator:', clf.best_estimator_)
    print('Best Estimator: PFERM(C={}, gamma={})'.
          format(clf.best_estimator_.C, clf.best_estimator_.gamma))

    # Accuracy and Fairness
    y_predict = clf.predict(dataset_test.data)
    pred = clf.predict(dataset_test.data)
    pred_train = clf.predict(dataset_train.data)
    print('Accuracy test:', accuracy_score(dataset_test.target, pred))
    print('Accuracy train:', accuracy_score(dataset_train.target, pred_train))
    # Fairness measure
    EO_train = equalized_odds_measure_TP(dataset_train, clf, [sensible_feature], ylabel=1)
    EO_test = equalized_odds_measure_TP(dataset_test, clf, [sensible_feature], ylabel=1)
    print('DEO test:', np.abs(EO_test[sensible_feature][sensible_feature_values[0]] -
                              EO_test[sensible_feature][sensible_feature_values[1]]))
    print('DEO train:', np.abs(EO_train[sensible_feature][sensible_feature_values[0]] -
                               EO_train[sensible_feature][sensible_feature_values[1]]))

    e = int(time.perf_counter() - start_time)
    print('Elapsed Time: {:02d}:{:02d}:{:02d}'.format(e // 3600, (e % 3600 // 60), e % 60))
