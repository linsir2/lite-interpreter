# Generated from src/kag/compiler/grammar/KnowledgeSpec.g4 by ANTLR 4.13.2
# encoding: utf-8
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
	from typing import TextIO
else:
	from typing.io import TextIO

def serializedATN():
    return [
        4,1,7,48,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,1,0,1,0,
        1,0,1,0,1,0,1,0,1,0,1,0,1,0,3,0,22,8,0,1,1,1,1,4,1,26,8,1,11,1,12,
        1,27,1,2,1,2,4,2,32,8,2,11,2,12,2,33,1,3,1,3,4,3,38,8,3,11,3,12,
        3,39,1,4,1,4,1,4,1,4,1,5,1,5,1,5,0,0,6,0,2,4,6,8,10,0,1,1,0,5,6,
        46,0,21,1,0,0,0,2,23,1,0,0,0,4,29,1,0,0,0,6,35,1,0,0,0,8,41,1,0,
        0,0,10,45,1,0,0,0,12,13,3,2,1,0,13,14,5,0,0,1,14,22,1,0,0,0,15,16,
        3,4,2,0,16,17,5,0,0,1,17,22,1,0,0,0,18,19,3,6,3,0,19,20,5,0,0,1,
        20,22,1,0,0,0,21,12,1,0,0,0,21,15,1,0,0,0,21,18,1,0,0,0,22,1,1,0,
        0,0,23,25,5,1,0,0,24,26,3,8,4,0,25,24,1,0,0,0,26,27,1,0,0,0,27,25,
        1,0,0,0,27,28,1,0,0,0,28,3,1,0,0,0,29,31,5,2,0,0,30,32,3,8,4,0,31,
        30,1,0,0,0,32,33,1,0,0,0,33,31,1,0,0,0,33,34,1,0,0,0,34,5,1,0,0,
        0,35,37,5,3,0,0,36,38,3,8,4,0,37,36,1,0,0,0,38,39,1,0,0,0,39,37,
        1,0,0,0,39,40,1,0,0,0,40,7,1,0,0,0,41,42,5,5,0,0,42,43,5,4,0,0,43,
        44,3,10,5,0,44,9,1,0,0,0,45,46,7,0,0,0,46,11,1,0,0,0,4,21,27,33,
        39
    ]

class KnowledgeSpecParser ( Parser ):

    grammarFileName = "KnowledgeSpec.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "'RULE'", "'METRIC'", "'FILTER'", "'='" ]

    symbolicNames = [ "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                      "<INVALID>", "KEY", "VALUE", "WS" ]

    RULE_spec = 0
    RULE_ruleSpec = 1
    RULE_metricSpec = 2
    RULE_filterSpec = 3
    RULE_pair = 4
    RULE_scalar = 5

    ruleNames =  [ "spec", "ruleSpec", "metricSpec", "filterSpec", "pair", 
                   "scalar" ]

    EOF = Token.EOF
    T__0=1
    T__1=2
    T__2=3
    T__3=4
    KEY=5
    VALUE=6
    WS=7

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class SpecContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def ruleSpec(self):
            return self.getTypedRuleContext(KnowledgeSpecParser.RuleSpecContext,0)


        def EOF(self):
            return self.getToken(KnowledgeSpecParser.EOF, 0)

        def metricSpec(self):
            return self.getTypedRuleContext(KnowledgeSpecParser.MetricSpecContext,0)


        def filterSpec(self):
            return self.getTypedRuleContext(KnowledgeSpecParser.FilterSpecContext,0)


        def getRuleIndex(self):
            return KnowledgeSpecParser.RULE_spec

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterSpec" ):
                listener.enterSpec(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitSpec" ):
                listener.exitSpec(self)




    def spec(self):

        localctx = KnowledgeSpecParser.SpecContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_spec)
        try:
            self.state = 21
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [1]:
                self.enterOuterAlt(localctx, 1)
                self.state = 12
                self.ruleSpec()
                self.state = 13
                self.match(KnowledgeSpecParser.EOF)
                pass
            elif token in [2]:
                self.enterOuterAlt(localctx, 2)
                self.state = 15
                self.metricSpec()
                self.state = 16
                self.match(KnowledgeSpecParser.EOF)
                pass
            elif token in [3]:
                self.enterOuterAlt(localctx, 3)
                self.state = 18
                self.filterSpec()
                self.state = 19
                self.match(KnowledgeSpecParser.EOF)
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class RuleSpecContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def pair(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(KnowledgeSpecParser.PairContext)
            else:
                return self.getTypedRuleContext(KnowledgeSpecParser.PairContext,i)


        def getRuleIndex(self):
            return KnowledgeSpecParser.RULE_ruleSpec

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterRuleSpec" ):
                listener.enterRuleSpec(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitRuleSpec" ):
                listener.exitRuleSpec(self)




    def ruleSpec(self):

        localctx = KnowledgeSpecParser.RuleSpecContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_ruleSpec)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 23
            self.match(KnowledgeSpecParser.T__0)
            self.state = 25 
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while True:
                self.state = 24
                self.pair()
                self.state = 27 
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if not (_la==5):
                    break

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class MetricSpecContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def pair(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(KnowledgeSpecParser.PairContext)
            else:
                return self.getTypedRuleContext(KnowledgeSpecParser.PairContext,i)


        def getRuleIndex(self):
            return KnowledgeSpecParser.RULE_metricSpec

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterMetricSpec" ):
                listener.enterMetricSpec(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitMetricSpec" ):
                listener.exitMetricSpec(self)




    def metricSpec(self):

        localctx = KnowledgeSpecParser.MetricSpecContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_metricSpec)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 29
            self.match(KnowledgeSpecParser.T__1)
            self.state = 31 
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while True:
                self.state = 30
                self.pair()
                self.state = 33 
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if not (_la==5):
                    break

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class FilterSpecContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def pair(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(KnowledgeSpecParser.PairContext)
            else:
                return self.getTypedRuleContext(KnowledgeSpecParser.PairContext,i)


        def getRuleIndex(self):
            return KnowledgeSpecParser.RULE_filterSpec

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterFilterSpec" ):
                listener.enterFilterSpec(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitFilterSpec" ):
                listener.exitFilterSpec(self)




    def filterSpec(self):

        localctx = KnowledgeSpecParser.FilterSpecContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_filterSpec)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 35
            self.match(KnowledgeSpecParser.T__2)
            self.state = 37 
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while True:
                self.state = 36
                self.pair()
                self.state = 39 
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if not (_la==5):
                    break

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class PairContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def KEY(self):
            return self.getToken(KnowledgeSpecParser.KEY, 0)

        def scalar(self):
            return self.getTypedRuleContext(KnowledgeSpecParser.ScalarContext,0)


        def getRuleIndex(self):
            return KnowledgeSpecParser.RULE_pair

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterPair" ):
                listener.enterPair(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitPair" ):
                listener.exitPair(self)




    def pair(self):

        localctx = KnowledgeSpecParser.PairContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_pair)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 41
            self.match(KnowledgeSpecParser.KEY)
            self.state = 42
            self.match(KnowledgeSpecParser.T__3)
            self.state = 43
            self.scalar()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class ScalarContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def KEY(self):
            return self.getToken(KnowledgeSpecParser.KEY, 0)

        def VALUE(self):
            return self.getToken(KnowledgeSpecParser.VALUE, 0)

        def getRuleIndex(self):
            return KnowledgeSpecParser.RULE_scalar

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterScalar" ):
                listener.enterScalar(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitScalar" ):
                listener.exitScalar(self)




    def scalar(self):

        localctx = KnowledgeSpecParser.ScalarContext(self, self._ctx, self.state)
        self.enterRule(localctx, 10, self.RULE_scalar)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 45
            _la = self._input.LA(1)
            if not(_la==5 or _la==6):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx





