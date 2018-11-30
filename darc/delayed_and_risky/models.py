from scipy.stats import norm, bernoulli, halfnorm
import numpy as np
from bad.model import Model


# TODO: THESE UTILITY FUNCTIONS ARE IN MULTIPLE PLACES !!!
def prob_to_odds_against(probabilities):
    '''convert probabilities of getting reward to odds against getting it'''
    odds_against = (1 - probabilities) / probabilities
    return odds_against


def odds_against_to_probs(odds):
    probabilities = 1 / (1+odds)
    return probabilities


class MultiplicativeHyperbolic(Model):
    '''Hyperbolic risk discounting model
    The idea is that we hyperbolically discount ODDS AGAINST the reward
    
    Vanderveldt, A., Green, L., & Myerson, J. (2015). Discounting of monetary
    rewards that are both delayed and probabilistic: delay and probability 
    combine multiplicatively, not additively. Journal of Experimental Psychology: 
    Learning, Memory, and Cognition, 41(1), 148–162.
    http://doi.org/10.1037/xlm0000029
    '''

    prior = dict()
    prior['logk'] = norm(loc=np.log(1/365), scale=2)
    # h=1 (ie logh=0) equates to risk neutral
    prior['logh'] = norm(loc=0, scale=1)
    prior['α'] = halfnorm(loc=0, scale=3)
    θ_fixed = {'ϵ': 0.01}

    def calc_decision_variable(self, θ, data):
        VA = data['RA'].values * self._time_discount_func(data['DA'].values, θ) * self._odds_discount_func(data['PA'].values, θ)
        VB = data['RB'].values * self._time_discount_func(data['DB'].values, θ) * self._odds_discount_func(data['PB'].values, θ)
        return VB - VA
    
    @staticmethod
    def _time_discount_func(delay, θ):
        k = np.exp(θ['logk'].values)
        return np.divide(1, (1 + k * delay))

    @staticmethod
    def _odds_discount_func(probabilities, θ):
        # transform logh to h
        h = np.exp(θ['logh'].values)
        # convert probability to odds against
        odds_against = prob_to_odds_against(probabilities)
        return np.divide(1, (1 + h * odds_against))
