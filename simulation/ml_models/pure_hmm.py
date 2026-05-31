"""
simulation/ml_models/pure_hmm.py
────────────────────────────────────────────────────────────────────────────
Pure Python / NumPy Hidden Markov Model (HMM) implementation.
Replaces hmmlearn which requires Microsoft C++ Build Tools on Windows.

This is a Gaussian HMM (Baum-Welch EM training) with:
  - 3 hidden states (RANGING, TRENDING, VOLATILE)
  - Diagonal covariance (simpler, faster, avoids singular matrices)
  - No external C extensions required

Compatible with: Python 3.10+ and numpy (already installed with MetaTrader5)

Usage:
    hmm = GaussianHMM(n_states=3, n_iter=100)
    hmm.fit(X)                          # X: (T, n_features) array
    states = hmm.predict(X)             # Viterbi decoding
    probs  = hmm.predict_proba(X)       # Posterior probs per time step
"""

import math
import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("PureHMM")


class GaussianHMM:
    """
    Gaussian Hidden Markov Model with diagonal covariance.
    Trained via Baum-Welch (EM) algorithm.
    Pure NumPy — no C extensions required.
    """

    def __init__(self, n_states: int = 3, n_iter: int = 100,
                 tol: float = 1e-4, random_state: int = 42):
        self.n_states = n_states
        self.n_iter   = n_iter
        self.tol      = tol
        self.rng      = np.random.RandomState(random_state)

        # Parameters (set after fit)
        self.pi_    = None   # Initial state distribution (n_states,)
        self.A_     = None   # Transition matrix (n_states, n_states)
        self.means_ = None   # Emission means (n_states, n_features)
        self.covs_  = None   # Emission covariances (n_states, n_features) — diagonal

    # ── Training (Baum-Welch EM) ───────────────────────────────────────────────

    def fit(self, X: np.ndarray) -> "GaussianHMM":
        """
        Fit HMM to observation sequence X using Baum-Welch EM.
        X: array of shape (T, n_features)
        """
        X = np.asarray(X, dtype=float)
        T, d = X.shape
        K = self.n_states

        # ── Initialize parameters ──────────────────────────────────────────────
        # Random k-means-like initialization for means
        idx = self.rng.choice(T, K, replace=False)
        self.means_ = X[idx].copy()
        self.covs_  = np.ones((K, d)) * np.var(X, axis=0) + 1e-6
        self.pi_    = np.ones(K) / K
        self.A_     = np.ones((K, K)) / K

        log_likelihood_prev = -np.inf

        for iteration in range(self.n_iter):
            # ── E-step: Forward-Backward ───────────────────────────────────────
            log_B = self._log_emission(X)           # (T, K)
            log_alpha = self._forward(log_B)         # (T, K)
            log_beta  = self._backward(log_B)        # (T, K)

            # Log-likelihood
            log_likelihood = _logsumexp(log_alpha[-1])

            # Posterior: gamma[t, k] = P(z_t = k | X)
            log_gamma = log_alpha + log_beta
            log_gamma -= _logsumexp_vec(log_gamma)   # Normalize rows
            gamma = np.exp(log_gamma)                # (T, K)

            # xi[t, i, j] = P(z_t=i, z_{t+1}=j | X)
            log_xi = (log_alpha[:-1, :, None] +
                      self.A_log_[None, :, :] +
                      log_B[1:, None, :] +
                      log_beta[1:, None, :])         # (T-1, K, K)
            log_xi -= _logsumexp_vec(log_xi.reshape(T-1, K*K)).reshape(T-1, 1, 1)
            xi = np.exp(log_xi)                      # (T-1, K, K)

            # ── M-step: Update parameters ──────────────────────────────────────
            # Initial state
            self.pi_ = gamma[0] + 1e-10
            self.pi_ /= self.pi_.sum()

            # Transition matrix
            A_num = xi.sum(axis=0) + 1e-10           # (K, K)
            self.A_ = A_num / A_num.sum(axis=1, keepdims=True)

            # Emission means and covariances
            gamma_sum = gamma.sum(axis=0) + 1e-10    # (K,)
            self.means_ = (gamma[:, :, None] * X[:, None, :]).sum(axis=0) / gamma_sum[:, None]
            diff = X[:, None, :] - self.means_[None, :, :]  # (T, K, d)
            self.covs_  = (gamma[:, :, None] * diff**2).sum(axis=0) / gamma_sum[:, None] + 1e-6

            # Check convergence
            delta = abs(log_likelihood - log_likelihood_prev)
            if delta < self.tol:
                logger.debug(f"[HMM] Converged at iteration {iteration} (δLL={delta:.2e})")
                break
            log_likelihood_prev = log_likelihood

        logger.debug(f"[HMM] Final log-likelihood: {log_likelihood:.4f}")
        return self

    # ── Decoding (Viterbi) ─────────────────────────────────────────────────────

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Viterbi decoding — returns most likely state sequence."""
        X = np.asarray(X, dtype=float)
        T = len(X)
        K = self.n_states
        log_B = self._log_emission(X)
        A_log = np.log(self.A_ + 1e-300)

        # Viterbi DP
        delta = np.full((T, K), -np.inf)
        psi   = np.zeros((T, K), dtype=int)

        delta[0] = np.log(self.pi_ + 1e-300) + log_B[0]
        for t in range(1, T):
            scores = delta[t-1][:, None] + A_log       # (K, K)
            psi[t]   = scores.argmax(axis=0)
            delta[t] = scores.max(axis=0) + log_B[t]

        # Backtrack
        states = np.zeros(T, dtype=int)
        states[-1] = delta[-1].argmax()
        for t in range(T - 2, -1, -1):
            states[t] = psi[t+1, states[t+1]]

        return states

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Returns posterior state probabilities (T, K)."""
        X = np.asarray(X, dtype=float)
        log_B = self._log_emission(X)
        log_alpha = self._forward(log_B)
        log_beta  = self._backward(log_B)
        log_gamma = log_alpha + log_beta
        log_gamma -= _logsumexp_vec(log_gamma)
        return np.exp(log_gamma)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _log_emission(self, X: np.ndarray) -> np.ndarray:
        """Log probability of each observation under each state's Gaussian. (T, K)"""
        T, d = X.shape
        K = self.n_states
        log_B = np.zeros((T, K))
        for k in range(K):
            mu    = self.means_[k]
            sigma = self.covs_[k]
            log_det = np.sum(np.log(sigma))
            diff    = X - mu
            mahal   = np.sum(diff**2 / sigma, axis=1)
            log_B[:, k] = -0.5 * (d * math.log(2 * math.pi) + log_det + mahal)
        return log_B

    def _forward(self, log_B: np.ndarray) -> np.ndarray:
        """Log-scale forward algorithm."""
        T, K = log_B.shape
        log_alpha = np.full((T, K), -np.inf)
        log_alpha[0] = np.log(self.pi_ + 1e-300) + log_B[0]
        A_log = self.A_log_
        for t in range(1, T):
            for j in range(K):
                log_alpha[t, j] = _logsumexp(log_alpha[t-1] + A_log[:, j]) + log_B[t, j]
        return log_alpha

    def _backward(self, log_B: np.ndarray) -> np.ndarray:
        """Log-scale backward algorithm."""
        T, K = log_B.shape
        log_beta = np.full((T, K), -np.inf)
        log_beta[-1] = 0.0
        A_log = self.A_log_
        for t in range(T - 2, -1, -1):
            for i in range(K):
                log_beta[t, i] = _logsumexp(A_log[i] + log_B[t+1] + log_beta[t+1])
        return log_beta

    @property
    def A_log_(self) -> np.ndarray:
        return np.log(self.A_ + 1e-300)

    # ── Serialization ──────────────────────────────────────────────────────────

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "GaussianHMM":
        with open(path, "rb") as f:
            return pickle.load(f)


# ── Math Utilities ─────────────────────────────────────────────────────────────

def _logsumexp(a: np.ndarray) -> float:
    """Numerically stable log-sum-exp of a 1D array."""
    a_max = a.max()
    if np.isneginf(a_max):
        return float('-inf')
    return a_max + math.log(np.exp(a - a_max).sum())


def _logsumexp_vec(A: np.ndarray) -> np.ndarray:
    """Row-wise log-sum-exp for a 2D array."""
    a_max = A.max(axis=-1, keepdims=True)
    out = a_max.squeeze(-1) + np.log(np.exp(A - a_max).sum(axis=-1))
    return out[..., None]
