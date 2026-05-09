grammar KnowledgeSpec;

spec
    : ruleSpec EOF
    | metricSpec EOF
    | filterSpec EOF
    ;

ruleSpec
    : 'RULE' pair+
    ;

metricSpec
    : 'METRIC' pair+
    ;

filterSpec
    : 'FILTER' pair+
    ;

pair
    : KEY '=' scalar
    ;

scalar
    : KEY
    | VALUE
    ;

KEY
    : [a-zA-Z_]+
    ;

VALUE
    : ~[ \t\r\n=]+
    ;

WS
    : [ \t\r\n]+ -> skip
    ;
