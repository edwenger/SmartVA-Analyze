import logging
import os
import threading

from smartva import headers
from smartva import vaprep
from smartva import adultpresymptom
from smartva import adultsymptom
from smartva import adulttariff
from smartva import childpresymptom
from smartva import childsymptom
from smartva import childtariff
from smartva import neonatepresymptom
from smartva import neonatesymptom
from smartva import neonatetariff
from smartva import causegrapher
from smartva import csmfgrapher
from smartva import short_form_test
from smartva.loggers import warning_logger
from smartva.utils import status_notifier


class CompletionStatus(object):
    DONE = 0
    ABORT = 1


# Thread class that executes processing
class WorkerThread(threading.Thread):
    """
    Worker Thread Class.

    For status notifier updates, the following key: value pairs are supplied:
        progress: (value, [range]) - Update value of progress bar
        sub_progress: (value, [range]) - Update value of sub progress bar
    Note: If optional range is not present, the previous range should be used.
    """

    def __init__(self, input_file, hce, output_dir, freetext, malaria, country, completion_callback):
        """
        Init Worker Thread Class.
        :type input_file: str
        :type hce: bool
        :type output_dir: str
        :type freetext: bool
        :type malaria: bool
        :type country: str
        :type completion_callback: callable
        """
        threading.Thread.__init__(self)
        self._completion_callback = completion_callback
        self._want_abort = 0
        self.inputFilePath = input_file
        self.data = None
        self.hce = hce
        self.output_dir = output_dir
        self.freetext = freetext
        self.malaria = malaria
        self.country = country
        # This starts the thread running on creation, but you could
        # also make the GUI thread responsible for calling this

        warning_file_handler = logging.FileHandler(os.path.join(self.output_dir, 'warnings.txt'), mode='w', delay=True)
        warning_logger.addHandler(warning_file_handler)

        self.shortform = False

        self.start()

    def run(self):
        status_notifier.update({'progress': (0, 15), 'sub_progress': (0, 1)})

        intermediate_dir = self.output_dir + os.sep + "intermediate-files"
        figures_dir = self.output_dir + os.sep + "figures"

        if not os.path.exists(intermediate_dir):
            os.mkdir(intermediate_dir)
        if not os.path.exists(figures_dir):
            os.mkdir(figures_dir)

        self.shortFormTest = short_form_test.ShortFormTest(self.inputFilePath)
        self.shortform = self.shortFormTest.run()

        # TODO should only pass the file to these methods. you can figure out self.output_dir from the file
        # set up the function calls
        self.cleanheaders = headers.Headers(self.inputFilePath, intermediate_dir)
        self.prep = vaprep.VaPrep(intermediate_dir + os.sep + "cleanheaders.csv", intermediate_dir, self.shortform)
        self.adultpresym = adultpresymptom.PreSymptomPrep(intermediate_dir + os.sep + "adult-prepped.csv", intermediate_dir, self.shortform)
        self.adultsym = adultsymptom.AdultSymptomPrep(intermediate_dir + os.sep + "adult-presymptom.csv", intermediate_dir, self.shortform)
        self.adultresults = adulttariff.Tariff(intermediate_dir + os.sep + "adult-symptom.csv", self.output_dir, intermediate_dir, self.hce, self.freetext, self.malaria, self.country, self.shortform)
        self.childpresym = childpresymptom.PreSymptomPrep(intermediate_dir + os.sep + "child-prepped.csv", intermediate_dir, self.shortform)
        self.childsym = childsymptom.ChildSymptomPrep(intermediate_dir + os.sep + "child-presymptom.csv", intermediate_dir, self.shortform)
        self.childresults = childtariff.Tariff(intermediate_dir + os.sep + "child-symptom.csv", self.output_dir, intermediate_dir, self.hce, self.freetext, self.malaria, self.country, self.shortform)
        self.neonatepresym = neonatepresymptom.PreSymptomPrep(intermediate_dir + os.sep + "neonate-prepped.csv", intermediate_dir, self.shortform)
        self.neonatesym = neonatesymptom.NeonateSymptomPrep(intermediate_dir + os.sep + "neonate-presymptom.csv", intermediate_dir)
        self.neonateresults = neonatetariff.Tariff(intermediate_dir + os.sep + "neonate-symptom.csv", self.output_dir, intermediate_dir, self.hce, self.freetext, self.country, self.shortform)
        self.causegrapher = causegrapher.CauseGrapher(self.output_dir + os.sep + '$module-predictions.csv', figures_dir)
        self.csmfgrapher = csmfgrapher.CSMFGrapher(self.output_dir + os.sep + '$module-csmf.csv', figures_dir)

        # makes cleanheaders.csv
        hasdata = self.cleanheaders.run()
        if hasdata == 0 or self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes adult-prepped.csv, child-prepped.csv, neonate-prepped.csv
        # we have data at this point, so all of these files should have been created
        self.prep.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes adult-presymptom.csv
        adult_data = self.adultpresym.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes adult-symptom.csv
        if adult_data == 1:
            self.adultsym.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        #
        # creates adult output files
        if adult_data == 1:
            self.adultresults.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes child-presymptom.csv
        child_data = self.childpresym.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes child-symptom.csv
        if child_data == 1:
            self.childsym.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # creates child output files
        if child_data == 1:
            self.childresults.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes neonate-presymptom.csv
        # TODO:  right now this is the same as child presymptom, should probably just combine into one
        neonate_data = self.neonatepresym.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # makes neonate-symptom.csv
        if neonate_data == 1:
            self.neonatesym.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # creates neonate output files
        if neonate_data == 1:
            self.neonateresults.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # generate all cause graphs
        self.causegrapher.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        # generate all csmf graphs
        self.csmfgrapher.run()
        if self._want_abort == 1:
            self._complete(CompletionStatus.ABORT)
            return

        self._complete(CompletionStatus.DONE)
        return

    def abort(self):
        """abort worker thread."""
        # Method for use by main thread to signal an abort
        self._want_abort = 1
        self.cleanheaders.abort()
        self.prep.abort()
        self.adultpresym.abort()
        self.adultsym.abort()
        self.adultresults.abort()
        self.childpresym.abort()
        self.childsym.abort()
        self.childresults.abort()
        self.neonatepresym.abort()
        self.neonatesym.abort()
        self.neonateresults.abort()
        self.causegrapher.abort()
        self.csmfgrapher.abort()
        if self.data:
            self.data.setCancelled()

    def _complete(self, status):
        for handler in warning_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.close()
        status_notifier.update({'progress': (int(not status), 1), 'sub_progress': (int(not status), 1)})
        self._completion_callback(status)
