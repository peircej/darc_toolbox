from abc import ABC, abstractmethod
from collections import namedtuple
from bad.designs import DesignGeneratorABC, BayesianAdaptiveDesign
import pandas as pd
import numpy as np
import itertools
from bad.optimisation import design_optimisation
import matplotlib.pyplot as plt
import copy
import logging
import time
import random


DEFAULT_DB = np.concatenate([
    np.array([1, 2, 5, 10, 15, 30, 45])/24/60,
    np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 12])/24,
    np.array([1, 2, 3, 4, 5, 6, 7]),
    np.array([2, 3, 4])*7,
    np.array([3, 4, 5, 6, 8, 9])*30,
    np.array([1, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25])*365]).tolist()

# define useful data structures
Prospect = namedtuple('Prospect', ['reward', 'delay', 'prob'])
Design = namedtuple('Design', ['ProspectA', 'ProspectB'])

# helper functions
def design_tuple_to_df(design):
    ''' Convert the named tuple into a 1-row pandas dataframe'''
    trial_data = {'RA': design.ProspectA.reward,
                  'DA': design.ProspectA.delay,
                  'PA': design.ProspectA.prob,
                  'RB': design.ProspectB.reward,
                  'DB': design.ProspectB.delay,
                  'PB': design.ProspectB.prob}
    return pd.DataFrame(trial_data)

def df_to_design_tuple(df):
    ''' Convert 1-row pandas dataframe into named tuple'''
    RA = df.RA.values[0]
    DA = df.DA.values[0]
    PA = df.PA.values[0]
    RB = df.RB.values[0]
    DB = df.DB.values[0]
    PB = df.PB.values[0]
    chosen_design = Design(ProspectA=Prospect(reward=RA, delay=DA, prob=PA),
                           ProspectB=Prospect(reward=RB, delay=DB, prob=PB))
    return chosen_design


# CONCRETE BAD CLASSES BELOW -----------------------------------------------------------------

class DARCDesignGenerator(BayesianAdaptiveDesign, DesignGeneratorABC):
    '''
    A class for running DARC choice tasks with Bayesian Adaptive Design.
    '''

    def __init__(self, DA=[0], DB=DEFAULT_DB, RA=list(), RB=[100],
                 RA_over_RB=list(), PA=[1], PB=[1],
                 random_choice_dimension=None,
                 max_trials=20,
                 NO_REPEATS=False):
        super().__init__()

        self._input_type_validation(RA, DA, PA, RB, DB, PB, RA_over_RB)
        self._input_value_validation(PA, PB, DA, DB, RA_over_RB)

        self._DA = DA
        self._DB = DB
        self._RA = RA
        self._RB = RB
        self._PA = PA
        self._PB = PB
        self._RA_over_RB = RA_over_RB
        self.max_trials = max_trials
        self.random_choice_dimension = random_choice_dimension
        self.NO_REPEATS = NO_REPEATS

        self.generate_all_possible_designs()


    def _input_type_validation(self, RA, DA, PA, RB, DB, PB, RA_over_RB):
        # NOTE: possibly not very Pythonic
        assert isinstance(RA, list), "RA should be a list"
        assert isinstance(DA, list), "DA should be a list"
        assert isinstance(PA, list), "PA should be a list"
        assert isinstance(RB, list), "RB should be a list"
        assert isinstance(DB, list), "DB should be a list"
        assert isinstance(PB, list), "PB should be a list"
        assert isinstance(RA_over_RB, list), "RA_over_RB should be a list"

        # we expect EITHER values in RA OR values in RA_over_RB
        # assert (not RA) ^ (not RA_over_RB), "Expecting EITHER RA OR RA_over_RB as an"
        if not RA:
            assert not RA_over_RB is False, "If not providing list for RA, we expect a list for RA_over_RB"

        if not RA_over_RB:
            assert not RA is False, "If not providing list for RA_over_RB, we expect a list for RA"


    def _input_value_validation(self, PA, PB, DA, DB, RA_over_RB):
        '''Confirm values of provided design space specs are valid'''
        if np.any((np.array(PA) < 0) | (np.array(PA) > 1)):
            raise ValueError('Expect all values of PA to be between 0-1')

        if np.any((np.array(PB) < 0) | (np.array(PB) > 1)):
            raise ValueError('Expect all values of PB to be between 0-1')

        if np.any(np.array(DA) < 0):
            raise ValueError('Expecting all values of DA to be >= 0')

        if np.any(np.array(DB) < 0):
            raise ValueError('Expecting all values of DB to be >= 0')

        if np.any((np.array(RA_over_RB) < 0) | (np.array(RA_over_RB) > 1)):
            raise ValueError('Expect all values of RA_over_RB to be between 0-1')

    def get_next_design(self, model):

        if self.trial > self.max_trials - 1:
            return None
        start_time = time.time()
        logging.info(f'Getting design for trial {self.trial}')

        allowable_designs = self.refine_design_space(model)
        chosen_design_df, _ = design_optimisation(allowable_designs, model.predictive_y, model.θ)
        chosen_design_named_tuple = df_to_design_tuple(chosen_design_df)

        logging.debug(f'chosen design is: {chosen_design_named_tuple}')
        logging.info(f'get_next_design() took: {time.time()-start_time:1.3f} seconds')
        return chosen_design_named_tuple

    def refine_design_space(self, model):
        '''A series of filter operations to refine down the space of designs which we
        do design optimisations on.'''

        allowable_designs = copy.copy(self.all_possible_designs)
        logging.debug(f'{allowable_designs.shape[0]} designs initially')

        if self.NO_REPEATS and self.trial>1:
            allowable_designs = remove_trials_already_run(
                allowable_designs, self.data.df.drop(columns=['R'])) # TODO: resolve this

        # apply a heuristic here to promote good spread of designs based on domain-specific
        # knowledge for DARC
        if self.random_choice_dimension is not None:
            allowable_designs = choose_one_along_design_dimension(
                allowable_designs, self.random_choice_dimension)
            logging.debug(
                f'{allowable_designs.shape[0]} designs remain after choose_one_along_design_dimension with {self.random_choice_dimension}')

        allowable_designs = remove_highly_predictable_designs(
            allowable_designs, model)

        if allowable_designs.shape[0] == 0:
            logging.error(f'No ({allowable_designs.shape[0]}) designs left')

        if allowable_designs.shape[0] < 10:
            logging.warning(f'Very few ({allowable_designs.shape[0]}) designs left')

        return allowable_designs


    def generate_all_possible_designs(self, assume_discounting=True):
        '''Create a dataframe of all possible designs (one design is one row)
        based upon the set of design variables (RA, DA, PA, RB, DB, PB)
        provided. We do this generation process ONCE. There may be additional
        trial-level processes which choose subsets of all of the possible
        designs. But here, we generate the largest set of designs that we
        will ever consider
        '''

        # Log the raw values to help with debugging
        logging.debug(f'provided RA = {self._RA}')
        logging.debug(f'provided DA = {self._DA}')
        logging.debug(f'provided PA = {self._PA}')
        logging.debug(f'provided RB = {self._RB}')
        logging.debug(f'provided DB = {self._DB}')
        logging.debug(f'provided PB = {self._PB}')
        logging.debug(f'provided RA_over_RB = {self._RA_over_RB}')

        if not self._RA_over_RB:
            '''assuming we are not doing magnitude effect, as this is
            when we normally would be providing RA_over_RB values'''

            # NOTE: the order of the two lists below HAVE to be the same
            column_list = ['RA', 'DA', 'PA', 'RB', 'DB', 'PB']
            list_of_lists = [self._RA, self._DA, self._PA, self._RB, self._DB, self._PB]
            all_combinations = list(itertools.product(*list_of_lists))
            D = pd.DataFrame(all_combinations, columns=column_list)

        elif not self._RA:
            '''now assume we are dealing with magnitude effect'''

            # create all designs, but using RA_over_RB
            # NOTE: the order of the two lists below HAVE to be the same
            column_list = ['RA_over_RB', 'DA', 'PA', 'RB', 'DB', 'PB']
            list_of_lists = [self._RA_over_RB, self._DA, self._PA, self._RB, self._DB, self._PB]
            all_combinations = list(itertools.product(*list_of_lists))
            D = pd.DataFrame(all_combinations, columns=column_list)

            # now we will convert RA_over_RB to RA for each design then remove it
            D['RA'] = D['RB'] * D['RA_over_RB']
            D = D.drop(columns=['RA_over_RB'])

        else:
            logging.error('Failed to work out what we want. Confusion over RA and RA_over_RB')


        logging.debug(f'{D.shape[0]} designs generated initially')

        # eliminate any designs where DA>DB, because by convention ProspectB is our more delayed reward
        D.drop(D[D.DA > D.DB].index, inplace=True)
        logging.debug(f'{D.shape[0]} left after dropping DA>DB')

        if assume_discounting:
            D.drop(D[D.RB < D.RA].index, inplace=True)
            logging.debug(f'{D.shape[0]} left after dropping RB<RA')

        # NOTE: we may want to do further trimming and refining of the possible
        # set of designs, based upon domain knowledge etc.

        # check we actually have some designs!
        if D.shape[0] == 0:
            logging.error(f'No ({D.shape[0]}) designs generated!')

        # set the values
        self.all_possible_designs = D


def remove_trials_already_run(design_set, exclude_these):
    '''Take in a set of designs (design_set) and remove aleady run trials (exclude_these)
    Dropping duplicates will work in this situation because `exclude_these` is going to
    be a subset of `design_set`'''
    # see https://stackoverflow.com/a/40209800/5172570
    allowable_designs = pd.concat([design_set, exclude_these]).drop_duplicates(keep=False)
    logging.debug(f'{allowable_designs.shape[0]} designs after removing prior designs')
    return allowable_designs


def remove_highly_predictable_designs(allowable_designs, model):
    ''' Eliminate designs which are highly predictable as these will not be very informative '''
    θ_point_estimate = model.get_θ_point_estimate()

    # TODO: CHECK WE CAN EPSILON TO 0
    p_chose_B = model.predictive_y(θ_point_estimate, allowable_designs)
    # add p_chose_B as a column to allowable_designs
    allowable_designs['p_chose_B'] = pd.Series(p_chose_B)
    # label rows which are highly predictable
    threshold = 0.01  # TODO: Tom used a lower threshold of 0.005, but that was with epsilon=0
    highly_predictable = (allowable_designs['p_chose_B'] < threshold) | (
        allowable_designs['p_chose_B'] > 1 - threshold)
    allowable_designs['highly_predictable'] = pd.Series(highly_predictable)

    n_not_predictable = allowable_designs.size - sum(allowable_designs.highly_predictable)
    if n_not_predictable > 10:
        # drop the offending designs (rows)
        allowable_designs = allowable_designs.drop(
            allowable_designs[allowable_designs.p_chose_B < threshold].index)
        allowable_designs = allowable_designs.drop(
            allowable_designs[allowable_designs.p_chose_B > 1 - threshold].index)
    else:
        # take the 10 designs closest to p_chose_B=0.5
        # NOTE: This is not exactly the same as Tom's implementation which examines
        # VB-VA (which is the design variable axis) and also VA+VB (orthogonal to
        # the design variable axis)
        logging.warning('not many unpredictable designs, so taking the 10 closest to unpredictable')
        allowable_designs['badness'] = np.abs(0.5- allowable_designs.p_chose_B)
        allowable_designs.sort_values(by=['badness'], inplace=True)
        allowable_designs = allowable_designs[:10]

    allowable_designs.drop(columns=['p_chose_B'])
    logging.debug(f'{allowable_designs.shape[0]} designs after removing highly predicted designs')
    return allowable_designs


def choose_one_along_design_dimension(allowable_designs, design_dim_name):
    '''We are going to take one design dimension given by `design_dim_name` and randomly
    pick one of it's values and hold it constant by removing all others from the list of
    allowable_designs.
    The purpose of this is to promote variation along the chosen design dimension.
    Cutting down the set of allowable_designs which we do design optimisation on is a
    nice side-effect rather than a direct goal.
    '''
    unique_values = allowable_designs[design_dim_name].unique()
    chosen_value = random.choice(unique_values)
    # filter by chosen value of this dimension
    allowable_designs = allowable_designs.loc[allowable_designs[design_dim_name] == chosen_value]
    return allowable_designs
