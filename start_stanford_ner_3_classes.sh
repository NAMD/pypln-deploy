#!/bin/bash
#
# Copyright 2013 NAMD-EMAP-FGV
#
# This file is part of PyPLN. You can get more information at: http://pypln.org/.
#
# PyPLN is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PyPLN is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PyPLN.  If not, see <http://www.gnu.org/licenses/>.

NER_HOME="/srv/pypln/NER/stanford_ner"
JAR_PATH="$NER_HOME/stanford-ner.jar"
CLASSIFIER_PATH="$NER_HOME/classifiers/english.all.3class.distsim.crf.ser.gz"
PORT=4243

# For now we'll use a maximum heap size of 500M
java -mx500m -cp "$JAR_PATH" edu.stanford.nlp.ie.NERServer -port "$PORT" -loadClassifier "$CLASSIFIER_PATH"
