import abc
import collections
import csv
import math
import os
import pickle
from decimal import Decimal

import numpy as np

from smartva import config
from smartva.data_prep import DataPrep
from smartva.loggers import status_logger, warning_logger
from smartva.utils import status_notifier, LdapNotationParser
from smartva.utils.conversion_utils import value_or_default
from smartva.utils.utils import round5, int_or_float

CAUSE_NUM_KEY = 'va46'
CAUSE_NAME_KEY = 'gs_text46'
TARIFF_CAUSE_NUM_KEY = 'xs_name'

MAX_CAUSE_SYMPTOMS = 40

SID_KEY = 'sid'
AGE_KEY = 'real_age'
SEX_KEY = 'real_gender'

MALARIA_CAUSES = [
    29
]


def get_cause_num(cause):
    return int(cause.lstrip('cause'))


class ScoredVA(object):
    def __init__(self, cause_scores, cause, sid, age, sex):
        self.cause_scores = cause_scores  # dict of {"cause1" : value, "cause2" :...}
        self.cause = cause  # int
        self.rank_list = {}
        self.sid = sid
        self.age = age
        self.sex = sex

    def __getitem__(self, key):
        return self.__dict__[key]

    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __repr__(self):
        return 'sid={sid} age={age} gender={gender} cs={cause_scores} cause={cause} rl={rank_list}'.format(**self.__dict__)

    def __str__(self):
        return self.__repr__()


class TariffPrep(DataPrep):
    """Process prepared answers against validated VA data.

    The main goal of this step is to determine cause of death by comparing symptom scores to those in a uniform list
    of validated VAs.
    Steps to accomplish this goal:
        Read intermediate data file
        Drop answers based on user flags

    Notes:
        Processing pipelines must implement `_matches_undetermined_cause` method.
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self, input_file, output_dir, intermediate_dir, hce, free_text, malaria, country, short_form):
        DataPrep.__init__(self, input_file, output_dir, short_form)

        self.intermediate_dir = intermediate_dir

        self.hce = hce
        self.free_text = free_text
        self.malaria = malaria
        self.iso3 = country

        self.cause_list = []

        self._data_module = None

    @property
    def data_module(self):
        return self._data_module

    @data_module.setter
    def data_module(self, value):
        assert self._data_module is None
        self._data_module = value

        self.AGE_GROUP = self.data_module.AGE_GROUP

    @property
    def va_validated_filename(self):
        return os.path.join(config.basedir, 'validated-{:s}.csv'.format(self.AGE_GROUP))

    @property
    def undetermined_matrix_filename(self):
        return os.path.join(config.basedir, '{:s}_undetermined_weights-hce{:d}.csv'.format(self.AGE_GROUP, int(self.hce)))

    def run(self):
        status_logger.info('{:s} :: Processing tariffs'.format(self.AGE_GROUP.capitalize()))
        status_notifier.update({'progress': 1})

        # Headers are being dropped only from tariff matrix now because of the way we are iterating over the pruned
        # tariff data. It is unnecessary to drop headers from other matrices.
        drop_headers = {TARIFF_CAUSE_NUM_KEY}
        if not self.hce:
            drop_headers.update(self.data_module.HCE_DROP_LIST)
        if not self.free_text:
            drop_headers.update(self.data_module.FREE_TEXT)
        if self.short_form:
            drop_headers.update(self.data_module.SHORT_FORM_DROP_LIST)

        cause46_names = self.get_cause46_names()

        undetermined_matrix = self._get_undetermined_matrix()

        cause40s = self.get_cause40s(drop_headers)
        self.cause_list = sorted(cause40s.keys())

        # """ # Uncomment this line to read from the pickle.
        status_logger.info('{:s} :: Generating validated VA cause list.'.format(self.AGE_GROUP.capitalize()))
        va_validated_cause_list = self.get_va_cause_list(self.va_validated_filename, cause40s)

        with open(os.path.join(config.basedir, 'validated-{:s}.pickle'.format(self.AGE_GROUP)), 'wb') as f:
            pickle.dump(va_validated_cause_list, f)
        """
        with open(os.path.join(config.basedir, 'validated-{:s}.pickle'.format(self.AGE_GROUP)), 'rb') as f:
            va_validated_cause_list = pickle.load(f)
        # """

        uniform_list = self.generate_uniform_list(va_validated_cause_list, self.data_module.FREQUENCIES)

        status_logger.debug('{:s} :: Generating cutoffs'.format(self.AGE_GROUP.capitalize()))
        cutoffs = self.generate_cutoffs(uniform_list, self.data_module.CUTOFF_POS)

        # """ # Uncomment this line to read from the pickle. (For testing purposes.)
        status_logger.info('{:s} :: Generating VA cause list.'.format(self.AGE_GROUP.capitalize()))
        va_cause_list = self.get_va_cause_list(self.input_file_path, cause40s, self.data_module.DEFINITIVE_SYMPTOMS)

        status_logger.info('{:s} :: Generating cause rankings.'.format(self.AGE_GROUP.capitalize()))
        self.generate_cause_rankings(va_cause_list, uniform_list)

        with open(os.path.join(self.intermediate_dir, 'rank_list-{:s}.pickle'.format(self.AGE_GROUP)), 'wb') as f:
            pickle.dump(va_cause_list, f)
        """
        with open(os.path.join(self.intermediate_dir, 'rank_list-{:s}.pickle'.format(self.AGE_GROUP)), 'rb') as f:
            va_cause_list = pickle.load(f)
        # """

        self.write_external_ranks(va_cause_list)

        lowest_rank = len(uniform_list)

        self.identify_lowest_ranked_causes(va_cause_list, uniform_list, cutoffs, self.data_module.CAUSE_CONDITIONS,
                                           lowest_rank, self.data_module.UNIFORM_LIST_POS,
                                           self.data_module.MIN_CAUSE_SCORE)

        cause_counts = self.write_predictions(va_cause_list, undetermined_matrix, lowest_rank,
                                              self.data_module.CAUSE_REDUCTION, self.data_module.CAUSES, cause46_names)

        self.write_csmf(cause_counts)

        self.write_tariff_ranks(va_cause_list)

        self.write_tariff_scores(va_cause_list)

        return True

    def get_cause46_names(self):
        with open(os.path.join(config.basedir, '{:s}_cause_names.csv'.format(self.AGE_GROUP)), 'rU') as f:
            reader = csv.DictReader(f)
            cause46_names = {int(cause[CAUSE_NUM_KEY]): cause[CAUSE_NAME_KEY] for cause in reader}
        return cause46_names

    def get_cause40s(self, drop_headers):
        cause40s = {}
        with open(os.path.join(config.basedir, 'tariffs-{:s}.csv'.format(self.AGE_GROUP)), 'rU') as f:
            reader = csv.DictReader(f)

            for row in reader:
                cause_num = get_cause_num(row[TARIFF_CAUSE_NUM_KEY])

                items = {k: float(v) for k, v in row.items() if k not in drop_headers and not v == '0.0'}.items()
                cause40s[cause_num] = sorted(items, key=lambda _: math.fabs(float(_[1])), reverse=True)[
                                      :MAX_CAUSE_SYMPTOMS]
        return cause40s

    def get_va_cause_list(self, input_file, cause40s, definitive_symptoms=None):
        """Generate list of Scored VAs. Read va data file and calculate cause score for each cause.

        Args:
            input_file (str): Path of input file.
            cause40s (dict):
            definitive_symptoms (dict):

        Returns:
            list: List of Scored VAs.
        """
        va_cause_list = []
        with open(input_file, 'rb') as f:
            reader = csv.DictReader(f)
            matrix = [row for row in reader]

        status_notifier.update({'sub_progress': (0, len(matrix))})

        for index, row in enumerate(matrix):
            if self.want_abort:
                return False

            status_notifier.update({'sub_progress': (index,)})

            cause_dict = {}

            for cause, symptoms in cause40s.items():
                cause_dict[cause] = sum(round5(Decimal(v)) for k, v in symptoms if row[k] == '1')

            # This is added for pipelines with symptoms that clearly indicate a cause.
            # e.g. Neonate would be 'stillbirth' if 's20' is '1'.
            if definitive_symptoms:
                for symptom, cause in definitive_symptoms.items():
                    if row[symptom] == '1':
                        row[CAUSE_NUM_KEY] = cause

            va_cause_list.append(ScoredVA(cause_dict, row.get(CAUSE_NUM_KEY), row[SID_KEY],
                                          row.get(AGE_KEY), row.get(SEX_KEY)))

        status_notifier.update({'sub_progress': None})

        return va_cause_list

    def generate_uniform_list(self, va_cause_list, frequencies):
        """Generate a uniform list of validated Scored VAs from a list of frequencies.

        Args:
            va_cause_list (list): List of validated Scored VAs.
            frequencies (dict): Map of scored VA to frequency.

        Returns:
            list: Uniform list of validated VAs.
        """
        uniform_list = []
        for va in va_cause_list:
            uniform_list.extend([va] * frequencies[va.sid])

        for cause in self.cause_list:
            cause_list = sorted(uniform_list, key=lambda t: t.cause_scores[cause], reverse=True)
            for i, va in enumerate(cause_list):
                va.rank_list[cause] = i

        return uniform_list

    def generate_cutoffs(self, uniform_list, cutoff_pos):
        """Determine cutoff score for each cause. Write scores to a file.

        Args:
            uniform_list (list): Uniform list of validated VAs.
            cutoff_pos (int): Cutoff position.

        Returns:
            dict: Cutoff score for each cause.
        """
        cutoffs = {}
        with open(os.path.join(self.intermediate_dir, '{:s}-cutoffs.txt'.format(self.AGE_GROUP)), 'w') as f:
            for cause_num in self.cause_list:
                # Get the uniform list sorted by (reversed) cause_score and sid.
                sorted_cause_list = sorted(uniform_list, key=lambda va: (-va.cause_scores[cause_num], va.sid))

                # Create a list of indexes from the sorted cause list for each cause.
                # we add one because python is 0 indexed and stata is 1 indexed, so this will give us the same
                # numbers as the original stata tool
                local_list = [(i + 1) for i, va in enumerate(sorted_cause_list) if int(va.cause) == cause_num]

                # Find the index of the item at cutoff position.
                cutoffs[cause_num] = local_list[int(len(local_list) * cutoff_pos)]

                f.write('{} : {}\n'.format(cause_num, cutoffs[cause_num]))

        return cutoffs

    def generate_cause_rankings(self, va_cause_list, uniform_list):
        """Determine cause rankings by comparing
        Args:
            va_cause_list:
            uniform_list:

        Returns:

        """
        status_notifier.update({'sub_progress': (0, len(va_cause_list))})

        for index, va in enumerate(va_cause_list):
            status_notifier.update({'sub_progress': (index,)})

            for cause in self.cause_list:
                if self.want_abort:
                    return

                # get the tariff score for this cause for this external VA
                death_score = va.cause_scores[cause]

                # make a list of tariffs of ALL validated VAs for this cause
                cause_scores = sorted((_.cause_scores[cause] for _ in (v_va for v_va in uniform_list)), reverse=True)

                tariffs = [math.fabs(_ - death_score) for _ in cause_scores]

                # add 1 because python is zero indexed, and stata is 1 indexed so we get the same
                # answer as the original stata tool
                va.rank_list[cause] = (np.where(np.array(tariffs) == min(tariffs))[0].mean()) + 1

        status_notifier.update({'sub_progress': None})

    def write_external_ranks(self, va_cause_list):
        """Write Scored VA ranks to a file.

        Args:
            va_cause_list (list): List of Scored VAs.
        """
        ranks = []
        for va in va_cause_list:
            rank_dict = {"sid": va.sid}
            rank_dict.update(va.rank_list)
            ranks.append(rank_dict)

        with open(os.path.join(self.intermediate_dir, '{:s}-external-ranks.csv'.format(self.AGE_GROUP)), 'wb') as f:
            writer = csv.DictWriter(f, sorted(ranks[0].keys(), key=lambda x: (isinstance(x, int), x)))
            writer.writeheader()
            writer.writerows(ranks)

    def _get_undetermined_matrix(self):
        """Return matrix undetermined weights read from the specified file.

        Returns:
            list: Undetermined weights data.
        """
        with open(self.undetermined_matrix_filename, 'rU') as f:
            reader = csv.DictReader(f)
            undetermined_matrix = [row for row in reader]
        return undetermined_matrix

    def identify_lowest_ranked_causes(self, va_cause_list, uniform_list, cutoffs, cause_conditions, lowest_rank,
                                      uniform_list_pos, min_cause_score):
        """Determine which causes are least likely by testing conditions.
        Only females ages 15-49 can have anaemia, hemorrhage, hypertensive disease, other pregnancy-related, or sepsis.
        Only males can have prostate cancer.
        Eliminate user specified causes (Malaria).

        Args:
            va_cause_list (list): List of Scored VAs.
            uniform_list (list): Uniform list of validated VAs.
            cutoffs (dict): Map of cutoff values for each cause.
            cause_conditions (dict): Conditions necessary for a given list of causes.
            lowest_rank (int): Value to assign to the least likely causes.
            uniform_list_pos (float): Reject causes above this position in the uniform list.
            min_cause_score (float): Reject causes under this threshold.
        """
        for va in va_cause_list:
            # if a VA has a tariff score less than 0 for a certain cause,
            # replace the rank for that cause with the lowest possible rank
            for cause in va.cause_scores:
                if float(va.cause_scores[cause]) < 0.0:
                    va.rank_list[cause] = lowest_rank

            lowest_cause_list = set()

            for condition, causes in cause_conditions.items():
                if not LdapNotationParser(condition, lambda t: value_or_default(va[t], int_or_float), int).parse():
                    lowest_cause_list.update(causes)

            if not self.malaria:
                lowest_cause_list.update(MALARIA_CAUSES)

            for cause_num in self.cause_list:
                if ((float(va.rank_list[cause_num]) > float(cutoffs[cause_num])) or
                        (float(va.rank_list[cause_num]) > float(len(uniform_list) * uniform_list_pos)) or
                    # EXPERIMENT: reject tariff scores less than a fixed amount as well
                        (float(va.cause_scores[cause_num]) <= min_cause_score)):
                    lowest_cause_list.add(cause_num)

            for cause_num in lowest_cause_list:
                va.rank_list[cause_num] = lowest_rank

    def write_predictions(self, va_cause_list, undetermined_matrix, lowest_rank, cause_reduction, cause34_names, cause46_names):
        """Determine cause predictions and write to a file. Return cause count.

        Args:
            va_cause_list (list): List of Scored VAs.
            undetermined_matrix (list): Matrix of undetermined cause weights.
            lowest_rank (int): Lowest possible rank (highest value, length of uniform list).
            cause_reduction (dict): Map to reduce cause46 values to cause34.
            cause34_names (dict): Cause34 cause names for prediction output.
            cause46_names (dict): Cause46 cause names for warning messages.

        Returns:
            collections.Counter: Dict of cause counts.
        """
        cause_counts = collections.Counter()
        with open(os.path.join(self.output_dir, '{:s}-predictions.csv'.format(self.AGE_GROUP)), 'wb') as f:
            writer = csv.writer(f)
            writer.writerow([SID_KEY, 'cause', 'cause34', 'age', 'sex'])

            for va in va_cause_list:
                # Record causes already determined.
                cause34 = va.cause

                # If a cause is not yet determined and any cause is higher than the lowest rank:
                va_lowest_rank = min(va.rank_list.values())
                if va_lowest_rank < lowest_rank and not cause34:
                    # Extract the causes with the highest rank (lowest value). Choose first cause if multiple are found.
                    causes = np.extract(np.array(va.rank_list.values()) == va_lowest_rank, va.rank_list.keys())
                    cause34 = cause_reduction[int(causes[0])]

                    # Warn user if multiple causes are equally likely and which will be chosen.
                    if len(causes) > 1:
                        multiple_cause_list = [cause46_names[int(_)] for _ in causes]
                        warning_logger.info(
                            '{group:s} :: SID: {sid:s} had multiple causes {causes} predicted to be equally likely, '
                            'using \'{causes[0]:s}\'.'.format(group=self.AGE_GROUP.capitalize(), sid=va.sid,
                                                              causes=multiple_cause_list))

                # Count causes, for use in graphs
                cause34_name = cause34_names.get(cause34, 'Undetermined')
                if not cause34:
                    if self.iso3 is None:
                        cause_counts.update([cause34_name])
                    else:
                        # For undetermined, look up the values for each cause using keys (age, sex, country) and
                        # add them to the 'count' for that cause
                        # TODO - What to do if nothing matches?
                        for u_row in undetermined_matrix:
                            if (u_row['iso3'] == self.iso3 and u_row['sex'] == va.sex and
                                    self._matches_undetermined_cause(va, u_row)):
                                cause_counts.update({u_row['gs_text34']: float(u_row['weight'])})
                                break
                else:
                    cause_counts.update([cause34_name])

                writer.writerow([va.sid, cause34, cause34_name, va.age, va.sex])
        return cause_counts

    @abc.abstractmethod
    def _matches_undetermined_cause(self, va, u_row):
        """Determine if a undetermined cause matches conditions of a given Scored VA.

        Args:
            va (ScoredVA): Verbal Autopsy data.
            u_row (list): Row of data from the undetermined matrix.

        Returns:
            bool: True if conditions match.
        """
        pass

    def write_tariff_scores(self, va_cause_list):
        """Write Scored VA Tariff scores.

        Args:
            va_cause_list (list): List of Scored VAs.
        """
        with open(os.path.join(self.intermediate_dir, '{:s}-tariff-scores.csv'.format(self.AGE_GROUP)), 'wb') as f:
            writer = csv.writer(f)
            writer.writerow([SID_KEY] + self.cause_list)
            writer.writerows([[va.sid] + [va.cause_scores[cause] for cause in self.cause_list] for va in va_cause_list])

    def write_tariff_ranks(self, va_cause_list):
        """Write Scored VA Tariff ranks.

        Args:
            va_cause_list (list): List of Scored VAs.
        """
        with open(os.path.join(self.intermediate_dir, '{:s}-tariff-ranks.csv'.format(self.AGE_GROUP)), 'wb') as f:
            writer = csv.writer(f)
            writer.writerow([SID_KEY] + self.cause_list)
            writer.writerows([[va.sid] + [va.rank_list[cause] for cause in self.cause_list] for va in va_cause_list])

    def write_csmf(self, cause_counts):
        """Write Scored VA cause counts.

        Args:
            cause_counts (dict): Map of causes to count.
        """
        cause_count_values = float(sum(cause_counts.values()))
        with open(os.path.join(self.output_dir, '{:s}-csmf.csv'.format(self.AGE_GROUP)), 'wb') as f:
            writer = csv.writer(f)
            writer.writerow(['cause', 'CSMF'])
            writer.writerows([[k, (v / cause_count_values)] for k, v in cause_counts.items()])
