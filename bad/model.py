'''
Model base class used by _any_ domain specific use of our Bayesian Adaptive Design package
'''


from abc import ABC, abstractmethod
from bad.inference import update_beliefs
from scipy.stats import norm, bernoulli
import logging
import time
import copy
import numpy as np
import pandas as pd
from random import random
from bad.triplot import tri_plot


# MODEL RELATED ====================================================================

# This is meant to be a very general model class. Therefore we have NOTHING specific
# about the design space or the parameters. The only thing we are assuming is that
# we have binary responses R

# NOTE: we are dealing with particles differently from the Matlab version of the code. We are
# only ever representing particles for the free parameters.
# Fixed parameters are just build in to the model class as scalars and are used by model
# functions when needed... they are never converted into a series of particles.


class Model(ABC):
    '''
    Model abstract base class. It does nothing on it's own, but it sketches out the core
    elements of _any_ model which we could use. To be clear, a model could be pretty much
    any computational/mathematical model which relates inputs (ie experimental designs)
    and model parameters to a behavioural response:
        response = f(design, parameters)

    We are only considering experimental paradigms where we have two possible responses.
    This is a simplification, but it also covers a very wide range of experiment classes
    including:
    a) psychophysics such as yes/no or 2AFC paradigms,
    b) decision making experiments with choices between 2 prospects

    I also impose that all of the models will involve a single decision variable. A choice
    function then operates on this decision variable in order to produce a probability of
    responding one way of the other.
    '''

    prior = dict()
    θ_fixed = dict()
    θ_true = None

    def __init__(self, n_particles):
        self.n_particles = int(n_particles)
        logging.debug(f'number of particles = {self.n_particles}')
        # FINISHING UP STUFF ==================================
        # NOTE `prior` and `θ_fixed` must be defined in the concrete model class before
        # we call this. I've not figures out how to demand these exist in this ABC yet
        self.parameter_names = self.prior.keys()
        self.θ = self._sample_from_prior()

    def update_beliefs(self, data):
        '''simply call the low-level `update_beliefs` function'''
        start_time = time.time()
        self.θ, _ = update_beliefs(self.p_log_pdf, self.θ, data, display=False)
        logging.info(
            f'update_beliefs() took: {time.time()-start_time:1.3f} seconds')
        return self

    def p_log_pdf(self, θ, data):
        """unnormalized posterior log( p(data|θ)p(θ) )
        θ: pd dataframe
        """
        return self.log_likelihood(θ, data) + self.log_prior_pdf(θ)

    def log_likelihood(self, θ, data):
        """
        Calculate the log liklihood of the data for given theta parameters.
        Σ log(p(data|θ))
        We are going to iterate over trials. For each one, we take the trial
        data and calculate the predictive_y. This gives us many values
        (correspoding to particles). We deal with these appropriately for
        'chose B' and 'chose A' trials. Then calculate the log
        likelihood, which involves summing the ll over trials so that we end
        up with a log likelihood value for all the particles.
        """

        n_trials, _ = data.shape
        n_particles, _ = θ.shape

        # TODO safety check... if no data, return ll = 0

        p_chose_B = np.zeros((n_particles, n_trials))
        R = data.R.values

        for trial in range(n_trials):
            trial_data = data.take([trial])
            if R[trial] is 1:  # meaning they chose option B
                p_chose_B[:, trial] = self.predictive_y( θ, trial_data)
            elif R[trial] is 0:  # meaning they chose option A
                p_chose_B[:, trial] = 1 - self.predictive_y(θ, trial_data)
            else:
                raise ValueError('Failing to identify response')

        ll = np.sum(np.log(p_chose_B), axis=1)
        return ll

    def log_prior_pdf(self, θ):
        """Evaluate the log prior density, log(p(θ)), for the values θ
        θ: dictionary, each key is a parameter name
        """
        # NOTE: avoid tears by copying θ. If we don't do this then we unintentionally
        # and undesirably update θ itself.
        log_prior = copy.copy(θ)
        for key in self.parameter_names:
            log_prior[key] = self.prior[key].logpdf(x=θ[key])

        log_prior = np.sum(log_prior, axis=1)  # sum over columns (parameters)
        return log_prior

    def _sample_from_prior(self):
        """Generate initial θ particles, by sampling from the prior"""
        particles_dict = {key: self.prior[key].rvs(size=self.n_particles)
            for key in self.parameter_names}
        return pd.DataFrame.from_dict(particles_dict)

    @abstractmethod
    def predictive_y(self, θ, data):
        '''
        Calculate the probability of chosing B. We need this to work in multiple
        contexts:

        INFERENCE CONTEXT
        input: θ has P rows, for example P = 5000 particles
        input: data has T rows, equal to number of trials we've run
        DESIRED output: p_chose_B is a P x 1 array

        OPTIMISATION CONTEXT
        input: θ has N rows (eg N=500)
        input: data has N rows
        DESIRED output: p_chose_B is a N x 1 array
        '''
        pass

    def get_simulated_response(self, design_df):
        '''
        Get simulated response for a given set of true parameter.
        This functionality is only needed when we are simulating experiment. It is not
        needed when we just want to run experiments on real participants.
        '''
        p_chose_B = self.predictive_y(self.θ_true, design_df)
        chose_B = random() < p_chose_B[0]
        return chose_B

    def export_posterior_histograms(self, filename):
        '''Export pdf of marginal posteriors
        filename: expecting this to be a string of filename and experiment date & time.
        '''
        tri_plot(self.θ, filename, θ_true=self.θ_true, priors=self.prior)


    def get_θ_point_estimate(self):
        '''return a point estimate (posterior median) for the model parameters'''
        median_series = self.θ.median(axis=0)
        return median_series.to_frame().T

    def get_θ_summary_stats(self, param_name):
        '''return summary stats for a given parameter'''

        summary_stats = {'entropy': [self.get_θ_entropy(param_name)],
                         'median': [self.θ[param_name].median()],
                         'mean': [self.θ[param_name].mean()],
                         'lower50': [self.θ[param_name].quantile(0.25)],
                         'upper50': [self.θ[param_name].quantile(0.75)],
                         'lower95': [self.θ[param_name].quantile(0.025)],
                         'upper95': [self.θ[param_name].quantile(1-0.025)]}
        summary_stats = pd.DataFrame.from_dict(summary_stats)
        summary_stats = summary_stats.add_prefix(param_name + '_')
        return summary_stats

    def get_θ_entropy(self, param_name):
        '''Calculate the entropy of the distribution of samples for the requested parameter.
        Calculate this based upon the normal distribution.'''
        samples = self.θ[param_name].values
        distribution = norm # TODO: ASSSUMES A NORMAL DISTRIBUTION !!!!!!!!!!!!!!!!!!!!!!!!!!!!
        return float(distribution.entropy(*distribution.fit(samples)))

    def generate_faux_true_params(self):
        '''Generate some true parameters based on the model's priors. This
        is used for doing testing parameter recovery where we need to generate
        true parameters for any given concrete model class.'''

        θ_dict = {}
        for key in self.parameter_names:
            θ_dict[key] = [self.prior[key].mean()]

        # θ_dict = {key: self.prior[key].median() for key in self.parameter_names}
        self.θ_true = pd.DataFrame.from_dict(θ_dict)
        return self
