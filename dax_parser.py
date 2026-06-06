import re

# -----------------------------------------------------------------------------
# 1. AST Nodes
# -----------------------------------------------------------------------------
class Node:
    pass

class Literal(Node):
    def __init__(self, value, is_string=False):
        self.value = value
        self.is_string = is_string
    def __repr__(self): return f'Literal({self.value})'

class ColumnRef(Node):
    def __init__(self, table, column):
        self.table = table
        self.column = column
    def __repr__(self): return f'ColumnRef({self.table}, {self.column})'

class MeasureRef(Node):
    def __init__(self, name):
        self.name = name
    def __repr__(self): return f'MeasureRef({self.name})'

class Identifier(Node):
    def __init__(self, name):
        self.name = name
    def __repr__(self): return f'Identifier({self.name})'

class FuncCall(Node):
    def __init__(self, name, args):
        self.name = name
        self.args = args
    def __repr__(self): return f'FuncCall({self.name}, {self.args})'

class BinOp(Node):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right
    def __repr__(self): return f'BinOp({self.left} {self.op} {self.right})'

class VarDef(Node):
    def __init__(self, name, expr):
        self.name = name
        self.expr = expr
    def __repr__(self): return f'VarDef({self.name} = {self.expr})'

class VarReturnBlock(Node):
    def __init__(self, variables, return_expr):
        self.variables = variables
        self.return_expr = return_expr
    def __repr__(self): return f'VarReturnBlock({self.variables}, {self.return_expr})'


# -----------------------------------------------------------------------------
# 2. Lexer
# -----------------------------------------------------------------------------
# Token types
TOK_EOF = 'EOF'
TOK_IDENT = 'IDENT'
TOK_FUNC = 'FUNC'
TOK_TABLE_COL = 'TABLE_COL'
TOK_MEASURE_COL = 'MEASURE_COL'
TOK_STRING = 'STRING'
TOK_NUMBER = 'NUMBER'
TOK_OP = 'OP'
TOK_LPAREN = 'LPAREN'
TOK_RPAREN = 'RPAREN'
TOK_COMMA = 'COMMA'
TOK_VAR = 'VAR'
TOK_RETURN = 'RETURN'

class Token:
    def __init__(self, type_, value):
        self.type = type_
        self.value = value
    def __repr__(self): return f"Token({self.type}, {repr(self.value)})"

def tokenize(text):
    tokens = []
    # Regular expressions for different token types
    # TABLE_COL: 'Table Name'[Column Name] or TableName[Column Name]
    table_col_re = r"('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_]*)\s*\[([^\]]+)\]"
    # MEASURE_COL: [Measure Name]
    measure_col_re = r"\[([^\]]+)\]"
    # STRING: "text"
    string_re = r'"([^"]*)"'
    # NUMBER: 123.45
    number_re = r'\b\d+(?:\.\d+)?\b'
    # OP: >=, <=, <>, ==, &&, ||, =, <, >, +, -, *, /, &
    op_re = r'>=|<=|<>|==|&&|\|\||[=<>+\-*/&]'
    # QUOTED_IDENT: 'Table Name'
    quoted_ident_re = r"'(?:[^']|'')+'"
    # IDENT: words (VAR, RETURN, function names, variable names)
    ident_re = r'[A-Za-z_][A-Za-z0-9_]*'

    # Combine regex
    pattern = re.compile(fr"""
        (?P<TABLE_COL>{table_col_re}) |
        (?P<MEASURE_COL>{measure_col_re}) |
        (?P<STRING>{string_re}) |
        (?P<NUMBER>{number_re}) |
        (?P<OP>{op_re}) |
        (?P<QUOTED_IDENT>{quoted_ident_re}) |
        (?P<LPAREN>\() |
        (?P<RPAREN>\)) |
        (?P<COMMA>,) |
        (?P<IDENT>{ident_re}) |
        (?P<WS>\s+)
    """, re.VERBOSE)

    pos = 0
    while pos < len(text):
        match = pattern.match(text, pos)
        if not match:
            # Skip unknown character (e.g., unexpected symbols)
            pos += 1
            continue
        
        kind = match.lastgroup
        value = match.group(kind)
        pos = match.end()

        if kind == 'WS':
            continue
            
        if kind == 'QUOTED_IDENT':
            # Strip quotes and replace double quotes
            val = value[1:-1].replace("''", "'")
            tokens.append(Token(TOK_IDENT, val))
            continue
            
        if kind == 'IDENT':
            v_upper = value.upper()
            if v_upper == 'VAR':
                tokens.append(Token(TOK_VAR, value))
            elif v_upper == 'RETURN':
                tokens.append(Token(TOK_RETURN, value))
            else:
                # Lookahead to see if it's a function call
                # Skip whitespace
                look_pos = pos
                while look_pos < len(text) and text[look_pos].isspace():
                    look_pos += 1
                if look_pos < len(text) and text[look_pos] == '(':
                    tokens.append(Token(TOK_FUNC, value))
                else:
                    tokens.append(Token(TOK_IDENT, value))
        elif kind == 'TABLE_COL':
            tbl = match.group(2)
            col = match.group(3)
            # Clean up single quotes from table name
            if tbl.startswith("'") and tbl.endswith("'"):
                tbl = tbl[1:-1].replace("''", "'")
            tokens.append(Token(TOK_TABLE_COL, (tbl, col)))
        elif kind == 'MEASURE_COL':
            col = value.strip('[]')
            tokens.append(Token(TOK_MEASURE_COL, col))
        elif kind == 'STRING':
            tokens.append(Token(TOK_STRING, value.strip('"')))
        else:
            tokens.append(Token(kind, value))

    tokens.append(Token(TOK_EOF, ''))
    return tokens

# -----------------------------------------------------------------------------
# 3. Recursive Descent Parser (Pratt-ish)
# -----------------------------------------------------------------------------
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        
        # Precedence levels
        self.precedence = {
            '||': 1,
            '&&': 2,
            '=': 3, '==': 3, '<>': 3, '<': 3, '>': 3, '<=': 3, '>=': 3,
            '&': 4,
            '+': 5, '-': 5,
            '*': 6, '/': 6,
        }

    def current(self):
        return self.tokens[self.pos]

    def consume(self, expected_type=None):
        tok = self.current()
        if expected_type and tok.type != expected_type:
            raise SyntaxError(f"Expected {expected_type}, got {tok.type} '{tok.value}'")
        self.pos += 1
        return tok

    def parse_expression(self, precedence=0):
        # 1. Parse VAR ... RETURN block
        if self.current().type == TOK_VAR:
            variables = []
            while self.current().type == TOK_VAR:
                self.consume(TOK_VAR)
                ident = self.consume(TOK_IDENT).value
                self.consume(TOK_OP) # Should be '='
                expr = self.parse_expression()
                variables.append(VarDef(ident, expr))
            
            # Consume RETURN
            if self.current().type == TOK_RETURN:
                self.consume(TOK_RETURN)
            
            return_expr = self.parse_expression()
            return VarReturnBlock(variables, return_expr)

        # 2. Parse Prefix / Literal
        left = self.parse_prefix()

        # 3. Parse Infix (Binary Ops)
        while self.current().type == TOK_OP:
            op = self.current().value
            op_prec = self.precedence.get(op, 0)
            if op_prec < precedence:
                break
            self.consume(TOK_OP)
            right = self.parse_expression(op_prec + 1)
            left = BinOp(left, op, right)

        return left

    def parse_prefix(self):
        tok = self.current()
        if tok.type == TOK_OP and tok.value == '-':
            self.consume()
            expr = self.parse_prefix()
            if isinstance(expr, Literal) and not expr.is_string:
                return Literal("-" + str(expr.value))
            return BinOp(Literal("0"), "-", expr)
        elif tok.type == TOK_NUMBER:
            self.consume()
            return Literal(tok.value)
        elif tok.type == TOK_STRING:
            self.consume()
            return Literal(tok.value, is_string=True)
        elif tok.type == TOK_TABLE_COL:
            self.consume()
            return ColumnRef(tok.value[0], tok.value[1])
        elif tok.type == TOK_MEASURE_COL:
            self.consume()
            return MeasureRef(tok.value)
        elif tok.type == TOK_IDENT:
            self.consume()
            if tok.value.upper() == 'NOT':
                expr = self.parse_prefix()
                return FuncCall('NOT', [expr])
            return Identifier(tok.value)
        elif tok.type == TOK_FUNC:
            func_name = self.consume().value
            self.consume(TOK_LPAREN)
            args = []
            if self.current().type != TOK_RPAREN:
                if self.current().type == TOK_COMMA:
                    args.append(Literal(""))
                else:
                    args.append(self.parse_expression())
                    
                while self.current().type == TOK_COMMA:
                    self.consume(TOK_COMMA)
                    if self.current().type in (TOK_COMMA, TOK_RPAREN):
                        args.append(Literal(""))
                    else:
                        args.append(self.parse_expression())
            self.consume(TOK_RPAREN)
            return FuncCall(func_name, args)
        elif tok.type == TOK_LPAREN:
            self.consume()
            expr = self.parse_expression()
            self.consume(TOK_RPAREN)
            return expr
        else:
            # Fallback for unexpected tokens to prevent hard crashing
            # We just consume it as a literal and move on
            self.consume()
            return Literal(tok.value)


# -----------------------------------------------------------------------------
# 4. Recursive Renderer
# -----------------------------------------------------------------------------
OPERATORS = {
    "=": "equals", "==": "equals", "<>": "does not equal",
    "&&": "AND", "||": "OR",
    "+": "plus", "-": "minus", "*": "times", "/": "divided by", "&": "concatenated with"
}

def _render_calculate(args, d, shape='block'):
    if len(args) == 0: return ""
    expr = render_node(args[0], d, shape='inline')
    
    if len(args) == 1: 
        if shape == 'inline': return expr
        return f"Calculates {expr}"
        
    conds = []
    for arg in args[1:]:
        if isinstance(arg, FuncCall) and arg.name.upper() in ("ALL", "REMOVEFILTERS", "ALLEXCEPT"):
            conds.append(render_node(arg, d, context='filter', shape='inline'))
        else:
            conds.append(render_node(arg, d, shape='inline'))
            
    if shape == 'inline':
        return f"({expr} evaluated with: {'; '.join(conds)})"
    else:
        res = f"Calculates {expr}, subject to the following conditions: <ul>"
        for c in conds:
            res += f"<li>{c}</li>"
        res += "</ul>"
        return res

def _render_if(args, d, shape='block'):
    if len(args) < 2: return ""
    cond = render_node(args[0], d, shape='inline')
    t_res = render_node(args[1], d, shape='inline')
    f_res = render_node(args[2], d, shape='inline') if len(args) > 2 else "empty (blank)"
    return f"Returns {t_res} IF {cond}, otherwise returns {f_res}"

def _render_eomonth(args, d, shape='block'):
    if len(args) < 2: return "the end of the month"
    date = render_node(args[0], d, shape='inline')
    offset_node = args[1]
    
    is_negative = False
    val_str = ""
    if isinstance(offset_node, Literal) and str(offset_node.value).startswith("-"):
        is_negative = True
        val_str = str(offset_node.value)[1:]
    elif isinstance(offset_node, BinOp) and offset_node.op == "-" and isinstance(offset_node.left, Literal) and offset_node.left.value == "0":
        is_negative = True
        val_str = render_node(offset_node.right, d, shape='inline')
    else:
        val_str = render_node(offset_node, d, shape='inline')
        
    if is_negative:
        return f"the end of the month {val_str} months before {date}"
    return f"the end of the month {val_str} months after {date}"

def _render_filter(args, d, shape='block'):
    if len(args) < 2: return ""
    table_str = render_node(args[0], d, context='table', shape='inline')
    cond_str = render_node(args[1], d, shape='inline')
    return f"the rows of {table_str} where {cond_str}"

def _render_switch(args, d, shape='block'):
    if len(args) < 2: return ""
    first_arg = args[0]
    is_true = False
    if isinstance(first_arg, FuncCall) and first_arg.name.upper() == "TRUE":
        is_true = True
    elif isinstance(first_arg, Identifier) and first_arg.name.upper() == "TRUE":
        is_true = True
        
    pairs = args[1:]
    res = []
    
    if is_true:
        i = 0
        while i < len(pairs):
            if i == len(pairs) - 1:
                res.append(f"otherwise {render_node(pairs[i], d, shape='inline')}")
                break
            else:
                c = render_node(pairs[i], d, shape='inline')
                r = render_node(pairs[i+1], d, shape='inline')
                res.append(f"when {c} then {r}")
                i += 2
        return "; ".join(res)
    else:
        expr_str = render_node(first_arg, d, shape='inline')
        i = 0
        while i < len(pairs):
            if i == len(pairs) - 1:
                res.append(f"otherwise {render_node(pairs[i], d, shape='inline')}")
                break
            else:
                c = render_node(pairs[i], d, shape='inline')
                r = render_node(pairs[i+1], d, shape='inline')
                res.append(f"when {expr_str} equals {c} then {r}")
                i += 2
        return "; ".join(res)

def _render_summarize(args, d, shape='block'):
    if len(args) < 3: return "SUMMARIZE(...)"
    table_str = render_node(args[0], d, shape='inline')
    
    group_cols = []
    i = 1
    while i < len(args) and isinstance(args[i], (ColumnRef, MeasureRef)):
        group_cols.append(render_node(args[i], d, shape='inline'))
        i += 1
        
    added = []
    while i < len(args)-1:
        name = render_node(args[i], d, shape='inline')
        expr = render_node(args[i+1], d, shape='inline')
        added.append(f"{name} = {expr}")
        i += 2
        
    res = f"{table_str}"
    if group_cols:
        res += f" grouped by {', '.join(group_cols)}"
    if added:
        res += f", adding {', '.join(added)}"
    return res

def _get_val(n):
    if hasattr(n, 'name'): return str(n.name)
    if hasattr(n, 'value'): return str(n.value)
    return ""

FUNC_TEMPLATES = {
    "AVERAGE":       lambda a, d, ctx, shp: f"the average of {render_node(a[0], d, shape='inline')}",
    "SUM":           lambda a, d, ctx, shp: f"the sum of {render_node(a[0], d, shape='inline')}",
    "MIN":           lambda a, d, ctx, shp: f"the minimum value of {render_node(a[0], d, shape='inline')}",
    "MAX":           lambda a, d, ctx, shp: f"the maximum value of {render_node(a[0], d, shape='inline')}",
    "DISTINCTCOUNT": lambda a, d, ctx, shp: f"the number of unique {render_node(a[0], d, shape='inline')}",
    "DIVIDE":        lambda a, d, ctx, shp: f"({render_node(a[0], d, shape='inline')} divided by {render_node(a[1], d, shape='inline')})" if shp == 'inline' else f"divides {render_node(a[0], d, shape='inline')} by {render_node(a[1], d, shape='inline')}",
    "VALUES":        lambda a, d, ctx, shp: f"each unique {render_node(a[0], d, shape='inline')}",
    "SELECTEDVALUE": lambda a, d, ctx, shp: f"the currently selected {render_node(a[0], d, shape='inline')}",
    "TODAY":         lambda a, d, ctx, shp: f"today's date",
    "BLANK":         lambda a, d, ctx, shp: f"empty (blank)",
    
    "DATESYTD":      lambda a, d, ctx, shp: f"the year-to-date period for {render_node(a[0], d, shape='inline')}",
    "DATESQTD":      lambda a, d, ctx, shp: f"the quarter-to-date period for {render_node(a[0], d, shape='inline')}",
    "DATESMTD":      lambda a, d, ctx, shp: f"the month-to-date period for {render_node(a[0], d, shape='inline')}",
    "SAMEPERIODLASTYEAR": lambda a, d, ctx, shp: f"the same period in the previous year for {render_node(a[0], d, shape='inline')}",
    "DATEADD":       lambda a, d, ctx, shp: f"{render_node(a[0], d, shape='inline')} shifted by {render_node(a[1], d, shape='inline')} {render_node(a[2], d, shape='inline')}" if len(a)>2 else "DATEADD(...)",
    "PARALLELPERIOD":lambda a, d, ctx, shp: f"{render_node(a[0], d, shape='inline')} shifted by {render_node(a[1], d, shape='inline')} {render_node(a[2], d, shape='inline')}s" if len(a)>2 else "PARALLELPERIOD(...)",
    "TOTALYTD":      lambda a, d, ctx, shp: f"the year-to-date total of {render_node(a[0], d, shape='inline')} for {render_node(a[1], d, shape='inline')}" if len(a)>1 else "TOTALYTD(...)",
    
    "RANKX":         lambda a, d, ctx, shp: f"the rank of {render_node(a[1], d, shape='inline')} within {render_node(a[0], d, shape='inline')}" + (", descending" if len(a)>3 and _get_val(a[3]).upper()=="DESC" else (", ascending" if len(a)>3 and _get_val(a[3]).upper()=="ASC" else "")) + (", dense ranking" if len(a)>4 and _get_val(a[4]).upper()=="DENSE" else ""),
    
    "CONCATENATEX":  lambda a, d, ctx, shp: f"the values of {render_node(a[1], d, shape='inline')} over {render_node(a[0], d, shape='inline')}" + (f", separated by {render_node(a[2], d, shape='inline')}" if len(a)>2 else "") + (f", ordered by {render_node(a[3], d, shape='inline')}" if len(a)>3 else "") + (" descending" if len(a)>4 and _get_val(a[4]).upper()=="DESC" else (" ascending" if len(a)>4 and _get_val(a[4]).upper()=="ASC" else "")),
    
    "KEEPFILTERS":   lambda a, d, ctx, shp: f"while keeping existing filters: {render_node(a[0], d, shape='inline')}",
    "USERELATIONSHIP": lambda a, d, ctx, shp: f"using the relationship between {render_node(a[0], d, shape='inline')} and {render_node(a[1], d, shape='inline')}" if len(a)>1 else "USERELATIONSHIP(...)",
    "TREATAS":       lambda a, d, ctx, shp: f"treating {render_node(a[0], d, shape='inline')} as values of {render_node(a[1], d, shape='inline')}" if len(a)>1 else "TREATAS(...)",
    "COUNTROWS":     lambda a, d, ctx, shp: f"the number of rows in {render_node(a[0], d, shape='inline')}",
    "ROUND":         lambda a, d, ctx, shp: f"({render_node(a[0], d, shape='inline')} rounded to {render_node(a[1], d, shape='inline')} decimals)" if shp == 'inline' else f"{render_node(a[0], d, shape='inline')} rounded to {render_node(a[1], d, shape='inline')} decimals",
    
    "ADDCOLUMNS":    lambda a, d, ctx, shp: f"{render_node(a[0], d, shape='inline')} with an added column {render_node(a[1], d, shape='inline')} = {render_node(a[2], d, shape='inline')}" if len(a)>2 else "ADDCOLUMNS(...)",
    "SELECTCOLUMNS": lambda a, d, ctx, shp: f"{render_node(a[0], d, shape='inline')} selecting column {render_node(a[1], d, shape='inline')} = {render_node(a[2], d, shape='inline')}" if len(a)>2 else "SELECTCOLUMNS(...)",
    "EARLIER":       lambda a, d, ctx, shp: f"the [{a[0].column}] of the current outer row" if isinstance(a[0], ColumnRef) else "the current outer row",
}

def render_node(node, descriptions_dict, context='scalar', shape='block'):
    if isinstance(node, Literal):
        if node.is_string: return f'"{node.value}"'
        return str(node.value)
        
    elif isinstance(node, Identifier):
        return f"<code>{node.name}</code>"
        
    elif isinstance(node, ColumnRef):
        clean_name = node.column
        desc = descriptions_dict.get(clean_name) or descriptions_dict.get(f"{node.table}[{node.column}]")
        if desc and str(desc).lower() not in ('nan', 'none', ''):
            return f"<strong>[{clean_name}]</strong> <em>({desc})</em>"
        return f"<strong>[{clean_name}]</strong>"
        
    elif isinstance(node, MeasureRef):
        clean_name = node.name
        desc = descriptions_dict.get(clean_name)
        if desc and str(desc).lower() not in ('nan', 'none', ''):
            return f"<strong>[{clean_name}]</strong> <em>({desc})</em>"
        return f"<strong>[{clean_name}]</strong>"
        
    elif isinstance(node, BinOp):
        left_str = render_node(node.left, descriptions_dict, shape='inline')
        right_str = render_node(node.right, descriptions_dict, shape='inline')
        op = node.op
        
        # Precedence mapping
        prec = {
            '||': 1, '&&': 2, '=': 3, '==': 3, '<>': 3, '<': 3, '>': 3, '<=': 3, '>=': 3,
            '&': 4, '+': 5, '-': 5, '*': 6, '/': 6
        }
        my_prec = prec.get(op, 0)
        
        if isinstance(node.left, BinOp):
            if prec.get(node.left.op, 0) < my_prec:
                left_str = f"({left_str})"
        if isinstance(node.right, BinOp):
            if prec.get(node.right.op, 0) <= my_prec:
                right_str = f"({right_str})"
        
        if op in (">=", "<=", ">", "<"):
            is_date = False
            right_node = node.right
            if isinstance(right_node, FuncCall) and right_node.name.upper() in ("TODAY", "EOMONTH", "DATE", "NOW"):
                is_date = True
            
            if op == ">=": op_str = "is on or after" if is_date else "is greater than or equal to"
            elif op == "<=": op_str = "is on or before" if is_date else "is less than or equal to"
            elif op == ">": op_str = "is after" if is_date else "is greater than"
            elif op == "<": op_str = "is before" if is_date else "is less than"
        else:
            op_str = OPERATORS.get(op, op)
            
        return f"{left_str} {op_str} {right_str}"
        
    elif isinstance(node, FuncCall):
        func_upper = node.name.upper()
        
        # Intercept AND/OR as functions
        if func_upper in ("AND", "OR"):
            if len(node.args) >= 2:
                # Convert to BinOp and render inline
                bo = BinOp(node.args[0], "&&" if func_upper == "AND" else "||", node.args[1])
                return render_node(bo, descriptions_dict, context, shape)
        
        if func_upper in ("ALL", "REMOVEFILTERS"):
            target = render_node(node.args[0], descriptions_dict, shape='inline') if node.args else "all tables"
            if context == 'filter':
                return f"ignores all filters on {target}"
            else:
                return f"{target} (with all filters removed)"
                
        if func_upper == "ALLEXCEPT":
            target = render_node(node.args[0], descriptions_dict, shape='inline') if node.args else "the table"
            except_args = ", ".join(render_node(x, descriptions_dict, shape='inline') for x in node.args[1:])
            if context == 'filter':
                return f"ignores all filters on {target} EXCEPT for {except_args}"
            else:
                return f"{target} (with all filters removed EXCEPT for {except_args})"
        
        if func_upper == "CALCULATE":
            return _render_calculate(node.args, descriptions_dict, shape)
            
        if func_upper == "IF":
            return _render_if(node.args, descriptions_dict, shape)
            
        if func_upper == "FILTER":
            return _render_filter(node.args, descriptions_dict, shape)
            
        if func_upper == "EOMONTH":
            return _render_eomonth(node.args, descriptions_dict, shape)
            
        if func_upper == "SWITCH":
            return _render_switch(node.args, descriptions_dict, shape)
            
        if func_upper == "SUMMARIZE":
            return _render_summarize(node.args, descriptions_dict, shape)
            
        if func_upper in ["SUMX", "AVERAGEX", "MINX", "MAXX"]:
            if len(node.args) >= 2:
                table_expr = render_node(node.args[0], descriptions_dict, context='table', shape='inline')
                inner_expr = render_node(node.args[1], descriptions_dict, shape='inline')
                action = func_upper[:-1].lower() # SUMX -> sum
                if shape == 'inline':
                    return f"(the {action} of {inner_expr} over {table_expr})"
                else:
                    return f"Returns the {action} over {table_expr} of the following: <div style='margin-left: 20px; border-left: 2px solid #ccc; padding-left: 10px;'>{inner_expr}</div>"

        tmpl = FUNC_TEMPLATES.get(func_upper)
        if tmpl:
            return tmpl(node.args, descriptions_dict, context, shape)
            
        args_str = ", ".join(render_node(a, descriptions_dict, shape='inline') for a in node.args)
        return f"<code>{node.name}({args_str})</code>"
        
    elif isinstance(node, VarReturnBlock):
        if shape == 'inline':
            v_strs = [f"{v.name} = {render_node(v.expr, descriptions_dict, shape='inline')}" for v in node.variables]
            return f"Variables defined: {'; '.join(v_strs)}. Returns: {render_node(node.return_expr, descriptions_dict, shape='inline')}"
            
        res = "<em>Variables defined: </em><ul>"
        for v in node.variables:
            res += f"<li><code>{v.name}</code> = {render_node(v.expr, descriptions_dict, shape='block')}</li>"
        res += "</ul>. <em>Returns: </em><br/>"
        res += render_node(node.return_expr, descriptions_dict, shape='block')
        return res
        
    return str(node)

def explain_dax(expr, descriptions_dict=None):
    """
    Parses a DAX expression into an AST and renders it as HTML-formatted human text.
    Returns the HTML string, or None if parsing fails.
    """
    if descriptions_dict is None:
        descriptions_dict = {}
        
    if not expr or not str(expr).strip():
        return None
        
    try:
        tokens = tokenize(expr)
        parser = Parser(tokens)
        ast = parser.parse_expression()
        res = render_node(ast, descriptions_dict)
        
        if parser.pos < len(parser.tokens) and parser.current().type != TOK_EOF:
            # Silent truncation detected. Output partial result and warning.
            unparsed = " ".join(t.value for t in parser.tokens[parser.pos:] if t.type != TOK_EOF)
            res += f"<br/><br/><span style='color: #d1242f;'><em>(⚠️ Partial explanation: complex syntax <code>{unparsed}</code> not fully supported)</em></span>"
            
        return res
    except Exception as e:
        print(f"DAX Parser failed on expr:\n{expr}\nError: {e}")
        return None

