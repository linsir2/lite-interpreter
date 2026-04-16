# Generated from src/kag/compiler/grammar/KnowledgeSpec.g4 by ANTLR 4.13.2
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
    from typing import TextIO
else:
    from typing.io import TextIO


def serializedATN():
    return [
        4,0,7,53,6,-1,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,2,
        6,7,6,1,0,1,0,1,0,1,0,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,1,2,1,
        2,1,2,1,2,1,2,1,2,1,3,1,3,1,4,4,4,38,8,4,11,4,12,4,39,1,5,4,5,43,
        8,5,11,5,12,5,44,1,6,4,6,48,8,6,11,6,12,6,49,1,6,1,6,0,0,7,1,1,3,
        2,5,3,7,4,9,5,11,6,13,7,1,0,3,3,0,65,90,95,95,97,122,4,0,9,10,13,
        13,32,32,61,61,3,0,9,10,13,13,32,32,55,0,1,1,0,0,0,0,3,1,0,0,0,0,
        5,1,0,0,0,0,7,1,0,0,0,0,9,1,0,0,0,0,11,1,0,0,0,0,13,1,0,0,0,1,15,
        1,0,0,0,3,20,1,0,0,0,5,27,1,0,0,0,7,34,1,0,0,0,9,37,1,0,0,0,11,42,
        1,0,0,0,13,47,1,0,0,0,15,16,5,82,0,0,16,17,5,85,0,0,17,18,5,76,0,
        0,18,19,5,69,0,0,19,2,1,0,0,0,20,21,5,77,0,0,21,22,5,69,0,0,22,23,
        5,84,0,0,23,24,5,82,0,0,24,25,5,73,0,0,25,26,5,67,0,0,26,4,1,0,0,
        0,27,28,5,70,0,0,28,29,5,73,0,0,29,30,5,76,0,0,30,31,5,84,0,0,31,
        32,5,69,0,0,32,33,5,82,0,0,33,6,1,0,0,0,34,35,5,61,0,0,35,8,1,0,
        0,0,36,38,7,0,0,0,37,36,1,0,0,0,38,39,1,0,0,0,39,37,1,0,0,0,39,40,
        1,0,0,0,40,10,1,0,0,0,41,43,8,1,0,0,42,41,1,0,0,0,43,44,1,0,0,0,
        44,42,1,0,0,0,44,45,1,0,0,0,45,12,1,0,0,0,46,48,7,2,0,0,47,46,1,
        0,0,0,48,49,1,0,0,0,49,47,1,0,0,0,49,50,1,0,0,0,50,51,1,0,0,0,51,
        52,6,6,0,0,52,14,1,0,0,0,4,0,39,44,49,1,6,0,0
    ]

class KnowledgeSpecLexer(Lexer):

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    T__0 = 1
    T__1 = 2
    T__2 = 3
    T__3 = 4
    KEY = 5
    VALUE = 6
    WS = 7

    channelNames = [ u"DEFAULT_TOKEN_CHANNEL", u"HIDDEN" ]

    modeNames = [ "DEFAULT_MODE" ]

    literalNames = [ "<INVALID>",
            "'RULE'", "'METRIC'", "'FILTER'", "'='" ]

    symbolicNames = [ "<INVALID>",
            "KEY", "VALUE", "WS" ]

    ruleNames = [ "T__0", "T__1", "T__2", "T__3", "KEY", "VALUE", "WS" ]

    grammarFileName = "KnowledgeSpec.g4"

    def __init__(self, input=None, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = LexerATNSimulator(self, self.atn, self.decisionsToDFA, PredictionContextCache())
        self._actions = None
        self._predicates = None


