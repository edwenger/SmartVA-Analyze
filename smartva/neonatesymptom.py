import csv
import copy
import os

from smartva.symptom_conversions import neonate_conversionVars
from smartva.loggers import status_logger

# removed because they don't exist in the form:


# variables generated by this step of the procedure
generatedHeaders = ['age', 's4991', 's4993', 's4994', 's5_1', 's6_1', 's8991', 's8992', 's11991', 's13_1', 's16_1',
                    's30991', 's46991', 's46992', 's49991', 's50991', 's51991', 's55991', 's56991', 's57991', 's58991',
                    's58992', 's58993', 's58994', 's69991', 's71991', 's76991', 's105_1', 'real_age', 'real_gender']

# missing? s31
durationSymptoms = ['s4', 's9', 's14', 's28', 's29', 's31', 's45', 's48', 's53', 's75', 's79', 's80', 's82', 's83',
                    's88', 's89', 's91', 's92']

durCutoffs = {'s4': 3, 's9': 2, 's14': 2500, 's28': 2, 's29': 3, 's31': 3, 's45': 255, 's48': .125, 's53': .2083333,
              's75': 2, 's79': 2, 's80': 2, 's82': 2, 's83': 2, 's88': 3, 's89': 2, 's91': 3, 's92': 2}

# not in electronic s32
binaryVars = ['s7', 's17', 's18', 's19', 's20', 's21', 's22', 's23', 's24', 's25', 's26', 's27', 's33', 's34', 's35',
              's36', 's37', 's38', 's39', 's40', 's41', 's42', 's43', 's47', 's52', 's54', 's59', 's60', 's61', 's62',
              's63', 's64', 's65', 's66', 's67', 's68', 's70', 's72', 's73', 's74', 's77', 's78', 's81', 's84', 's85',
              's86', 's87', 's90', 's93', 's94', 's95', 's96', 's97', 's98', 's99', 's100', 's101', 's102', 's103',
              's104', 's106', 's106', 's107', 's108', 's109', 's188', 's189', 's190']


class NeonateSymptomPrep(object):
    def __init__(self, input_file, output_dir):
        self.inputFilePath = input_file
        self.output_dir = output_dir
        self.want_abort = 0

    def run(self):
        reader = csv.reader(open(self.inputFilePath, 'rb'))
        adultwriter = csv.writer(open(self.output_dir + os.sep + 'neonate-symptom.csv', 'wb', buffering=0))

        matrix = list()
        headers = list()

        status_logger.info("Neonate :: Processing symptom data")

        first = 1
        # read in new .csv for processing
        # we add the generated headers later this time
        for row in reader:
            if first == 1:
                for col in row:
                    headers.append(col)
                first = 0
            else:
                matrix.append(row)

        # Add svars for text
        keys = neonate_conversionVars.keys()
        keys.extend(['s99991', 's999910', 's999911', 's999912', 's999913', 's999914', 's999915', 's999916', 's999917',
                     's999918', 's999919', 's99992', 's999920', 's999921', 's999922', 's999923', 's999924', 's999925',
                     's999926', 's999927', 's999928', 's999929', 's99993', 's999930', 's999931', 's999932', 's999933',
                     's999934', 's999935', 's999936', 's999937', 's99994', 's99995', 's99996', 's99997', 's99998',
                     's99999'])
        headers_copy = copy.deepcopy(headers)
        for col in headers_copy:
            if col not in keys:
                index = headers.index(col)
                for row in matrix:
                    del row[index]
                headers.remove(col)

        # now convert variable names
        for i, header in enumerate(headers):
            try:
                headers[i] = neonate_conversionVars[header]
            except KeyError:
                pass

        # add new variables and create space for them in the matrix
        for gen in generatedHeaders:
            headers.append(gen)
            for row in matrix:
                row.append("0")

        # new stuffs
        for row in matrix:
            index = headers.index('age')
            if row[headers.index('s4')] <= 6:
                row[index] = 0
            else:
                row[index] = .01

            # recode sex variable
            sex = row[headers.index('sex')]
            if sex == str(9) or sex == str(1):
                sex = 0
            elif sex == str(2):
                sex = 1
            row[headers.index('sex')] = sex

            # not in electronic
            # recode second sex variable
            # s15 = row[headers.index('s15')]
            #             if s15 == str(9) or s15 == str(1):
            #                 s15 = 0
            #             elif s15 == str(2):
            #                 s15 = 1
            #             row[headers.index('s15')] = s15

            s2 = row[headers.index('s2')]
            s3 = row[headers.index('s3')]
            s4 = row[headers.index('s4')]

            if s2 == str(999) and s3 == str(99) and s4 == str(99):
                s2 = ''
                s3 = ''
                s4 = ''
            else:
                if s2 == str(999):
                    s2 = 0
                if s3 == str(99):
                    s3 = 0
                if s4 == str(99):
                    s4 = 0

            s3 = int(s3) * 30
            if s4 == 0 and s3 != '':
                s4 = s3

            row[headers.index('s2')] = s2
            row[headers.index('s3')] = s3
            row[headers.index('s4')] = s4

            index = headers.index('s4')
            s4991index = headers.index('s4991')
            s4993index = headers.index('s4993')
            s4994index = headers.index('s4994')
            if float(row[index]) <= 0:
                row[s4991index] = 1
            elif float(row[index]) > 0 and float(row[index]) <= 2:
                row[s4993index] = 1
            elif float(row[index]) > 2:
                row[s4994index] = 1

            # make new variables to store the real age and gender, but do it after we've modified the sex
            # vars from 2, 1 to 1, 0
            ageindex = headers.index('real_age')
            genderindex = headers.index('real_gender')
            row[ageindex] = row[headers.index('s4')]
            row[genderindex] = row[headers.index('sex')]

            for sym in durationSymptoms:
                index = headers.index(sym)
                # replace the duration with 1000 if it is over 1000 and not missing
                if row[index] == '':
                    row[index] = 0
                elif float(row[index]) > 1000:
                    row[index] = 1000
                # use cutoffs to determine if they will be replaced with a 1 (were above or equal to the cutoff)
                if float(row[index]) >= durCutoffs[sym]:
                    row[index] = 1
                else:
                    row[index] = 0

            # dichotimize!
            index = headers.index('s5_1')
            val = row[headers.index('s5')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s6_1')
            val = row[headers.index('s6')]
            if val == '':
                val = '0'
            if val == '2' or val == '3':
                row[index] = '1'

            index = headers.index('s8991')
            val = row[headers.index('s8')]
            if val == '':
                val = '0'
            if val == '1':
                row[index] = '1'

            index = headers.index('s8992')
            val = row[headers.index('s8')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s11991')
            val = row[headers.index('s11')]
            if val == '':
                val = '0'
            if val == '4' or val == '5':
                row[index] = '1'

            index = headers.index('s13_1')
            val = row[headers.index('s13')]
            if val == '':
                val = '0'
            if val == '1' or val == '2':
                row[index] = '1'

            index = headers.index('s16_1')
            val = row[headers.index('s16')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s30991')
            val = row[headers.index('s30')]
            if val == '':
                val = '0'
            if val == '3' or val == '4':
                row[index] = '1'

            index = headers.index('s46991')
            val = row[headers.index('s46')]
            if val == '':
                val = '0'
            if val == '1':
                row[index] = '1'

            index = headers.index('s46992')
            val = row[headers.index('s46')]
            if val == '':
                val = '0'
            if val == '3':
                row[index] = '1'

            index = headers.index('s49991')
            val = row[headers.index('s49')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s50991')
            val = row[headers.index('s50')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s51991')
            val = row[headers.index('s51')]
            if val == '':
                val = '0'
            if val == '1' or val == '3':
                row[index] = '1'

            index = headers.index('s55991')
            val = row[headers.index('s55')]
            if val == '':
                val = '0'
            if val == '1' or val == '2':
                row[index] = '1'

            # not in electronic
            # index = headers.index('s56991')
            #             val = row[headers.index('s56')]
            #             if val == '':
            #                 val = 0
            #             else:
            #                 val = int(val)
            #             if (val == 4 or val == 5):
            #                 row[index] = 1

            index = headers.index('s57991')
            val = row[headers.index('s57')]
            if val == '':
                val = '0'
            if not (val == '1' or val == '2'):
                row[index] = '1'

            index = headers.index('s58991')
            val = row[headers.index('s58')]
            if val == '':
                val = '0'
            if val == '1':
                row[index] = '1'

            index = headers.index('s58992')
            val = row[headers.index('s58')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s58993')
            val = row[headers.index('s58')]
            if val == '':
                val = '0'
            if val == '3':
                row[index] = '1'

            index = headers.index('s58994')
            val = row[headers.index('s58')]
            if val == '':
                val = '0'
            if val == '4':
                row[index] = '1'

            index = headers.index('s69991')
            val = row[headers.index('s69')]
            if val == '':
                val = '0'
            if val == '3' or val == '4':
                row[index] = '1'

            index = headers.index('s71991')
            val = row[headers.index('s71')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s76991')
            val = row[headers.index('s76')]
            if val == '':
                val = '0'
            if val == '2':
                row[index] = '1'

            index = headers.index('s105_1')
            val = row[headers.index('s105')]
            if val == '':
                val = '0'
            # this works for strings, too
            if val > '1':
                row[index] = '1'

            # ensure all binary variables actually ARE 0 or 1:
            for var in binaryVars:
                val = row[headers.index(var)]
                if val == '' or val != '1':
                    row[headers.index(var)] = '0'

        # not in electronic s56
        # drop s15 because it's not there
        # drop 'age' because it was just used for a calculation, and will be replaced with a new 'age'
        droplist = ['s2', 's3', 's5', 's6', 's8', 's11', 's13', 's16', 's30', 's46', 's49', 's50', 's51', 's55', 's57',
                    's58', 's69', 's71', 's76', 's105', 'age']
        for d in droplist:
            index = headers.index(d)
            headers.remove(d)
            for row in matrix:
                del row[index]

        rename = {'s5_1': 's5', 's6_1': 's6', 's13_1': 's13', 's16_1': 's16', 's105_1': 's105', 's4': 'age'}
        for key in rename.keys():
            index = headers.index(key)
            headers[index] = rename[key]

        # makes s24-27 come from c3_03 instead of c1_19_N
        for row in matrix:
            s24 = headers.index('s24')
            s62 = headers.index('s62')
            row[s24] = row[s62]
            s25 = headers.index('s25')
            s63 = headers.index('s63')
            row[s25] = row[s63]
            s26 = headers.index('s26')
            s64 = headers.index('s64')
            row[s26] = row[s64]

        adultwriter.writerow(headers)
        for row in matrix:
            adultwriter.writerow(row)

        return 1

    def abort(self):
        self.want_abort = 1
