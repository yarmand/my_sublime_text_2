#===- cindex.py - Python Indexing Library Bindings -----------*- python -*--===#
#
#                     The LLVM Compiler Infrastructure
#
# This file is distributed under the University of Illinois Open Source
# License. See LICENSE.TXT for details.
#
#===------------------------------------------------------------------------===#

r"""
Clang Indexing Library Bindings
===============================

This module provides an interface to the Clang indexing library. It is a
low-level interface to the indexing library which attempts to match the Clang
API directly while also being "pythonic". Notable differences from the C API
are:

 * string results are returned as Python strings, not CXString objects.

 * null cursors are translated to None.

 * access to child cursors is done via iteration, not visitation.

The major indexing objects are:

  Index

    The top-level object which manages some global library state.

  TranslationUnit

    High-level object encapsulating the AST for a single translation unit. These
    can be loaded from .ast files or parsed on the fly.

  Cursor

    Generic object for representing a node in the AST.

  SourceRange, SourceLocation, and File

    Objects representing information about the input source.

Most object information is exposed using properties, when the underlying API
call is efficient.
"""

# TODO
# ====
#
# o API support for invalid translation units. Currently we can't even get the
#   diagnostics on failure because they refer to locations in an object that
#   will have been invalidated.
#
# o fix memory management issues (currently client must hold on to index and
#   translation unit, or risk crashes).
#
# o expose code completion APIs.
#
# o cleanup ctypes wrapping, would be nice to separate the ctypes details more
#   clearly, and hide from the external interface (i.e., help(cindex)).
#
# o implement additional SourceLocation, SourceRange, and File methods.

from ctypes import *
from common import error_message
import platform

isWin64 = False
if platform.system() == 'Windows':
    bits,linkage = platform.architecture()
    if bits=="64bit":
        isWin64 = True

def get_cindex_library():
    # FIXME: It's probably not the case that the library is actually found in
    # this location. We need a better system of identifying and loading the
    # CIndex library. It could be on path or elsewhere, or versioned, etc.
    import platform
    name = platform.system()
    if name == 'Darwin':
        return cdll.LoadLibrary('libclang.dylib')
    elif name == 'Windows':
        if isWin64:
            return cdll.LoadLibrary("libclang_x64.dll")
        return cdll.LoadLibrary('libclang.dll')
    else:
        try:
            # Try loading with absolute path first
            import os
            path = os.path.dirname(os.path.abspath(__file__))
            return cdll.LoadLibrary('%s/../libclang.so' % path)
        except:
            try:
                # See if there's one in the system path
                return cdll.LoadLibrary("libclang.so")
            except:
                import traceback
                traceback.print_exc()
                error_message("""\
It looks like libclang.so couldn't be loaded. On Linux you have to \
compile it yourself, or install it via your package manager. \
Please note that this plugin uses features from clang 3.0 so \
make sure that is the version you have installed.

Once installed, you need to copy libclang.so into the root of this \
plugin. See http://github.com/quarnster/SublimeClang for more details.
""")

# ctypes doesn't implicitly convert c_void_p to the appropriate wrapper
# object. This is a problem, because it means that from_parameter will see an
# integer and pass the wrong value on platforms where int != void*. Work around
# this by marshalling object arguments as void**.
c_object_p = POINTER(c_void_p)


lib = get_cindex_library()

### Structures and Utility Classes ###

class _CXString(Structure):
    """Helper for transforming CXString results."""

    _fields_ = [("spelling", c_char_p), ("free", c_int)]

    def __del__(self):
        _CXString_dispose(self)

    @staticmethod
    def from_result(res, fn, args):
        assert isinstance(res, _CXString)
        return _CXString_getCString(res)

class SourceLocation(Structure):
    """
    A SourceLocation represents a particular location within a source file.
    """
    _fields_ = [("ptr_data", c_void_p * 2), ("int_data", c_uint)]
    _data = None

    def _get_instantiation(self):
        if self._data is None:
            f, l, c, o = c_object_p(), c_uint(), c_uint(), c_uint()
            SourceLocation_loc(self, byref(f), byref(l), byref(c), byref(o))
            f = File(f) if f else None
            self._data = (f, int(l.value), int(c.value), int(o.value))
        return self._data

    @property
    def file(self):
        """Get the file represented by this source location."""
        return self._get_instantiation()[0]

    @property
    def line(self):
        """Get the line represented by this source location."""
        return self._get_instantiation()[1]

    @property
    def column(self):
        """Get the column represented by this source location."""
        return self._get_instantiation()[2]

    @property
    def offset(self):
        """Get the file offset represented by this source location."""
        return self._get_instantiation()[3]

    def __repr__(self):
        return "<SourceLocation file %r, line %r, column %r>" % (
            self.file.name if self.file else None, self.line, self.column)

class SourceRange(Structure):
    """
    A SourceRange describes a range of source locations within the source
    code.
    """
    _fields_ = [
        ("ptr_data", c_void_p * 2),
        ("begin_int_data", c_uint),
        ("end_int_data", c_uint)]

    # FIXME: Eliminate this and make normal constructor? Requires hiding ctypes
    # object.
    @staticmethod
    def from_locations(start, end):
        return SourceRange_getRange(start, end)

    @property
    def start(self):
        """
        Return a SourceLocation representing the first character within a
        source range.
        """
        return SourceRange_start(self)

    @property
    def end(self):
        """
        Return a SourceLocation representing the last character within a
        source range.
        """
        return SourceRange_end(self)

    def __repr__(self):
        return "<SourceRange start %r, end %r>" % (self.start, self.end)

class Diagnostic(object):
    """
    A Diagnostic is a single instance of a Clang diagnostic. It includes the
    diagnostic severity, the message, the location the diagnostic occurred, as
    well as additional source ranges and associated fix-it hints.
    """

    Ignored = 0
    Note    = 1
    Warning = 2
    Error   = 3
    Fatal   = 4

    severityNames = ["Ignored", "Note", "Warning", "Error", "Fatal"]

    def __init__(self, ptr):
        self.ptr = ptr

    def __del__(self):
        _clang_disposeDiagnostic(self)

    @property
    def severity(self):
        return _clang_getDiagnosticSeverity(self)

    @property
    def severityName(self):
        return self.severityNames[self.severity]

    @property
    def location(self):
        return _clang_getDiagnosticLocation(self)

    @property
    def spelling(self):
        return _clang_getDiagnosticSpelling(self)

    @property
    def disable_option(self):
        option = _CXString()
        _clang_getDiagnosticOption(self, byref(option))
        return _CXString_getCString(option)

    @property
    def ranges(self):
        class RangeIterator:
            def __init__(self, diag):
                self.diag = diag

            def __len__(self):
                return int(_clang_getDiagnosticNumRanges(self.diag))

            def __getitem__(self, key):
                if (key >= len(self)):
                    raise IndexError
                return _clang_getDiagnosticRange(self.diag, key)

        return RangeIterator(self)

    @property
    def fixits(self):
        class FixItIterator:
            def __init__(self, diag):
                self.diag = diag

            def __len__(self):
                return int(_clang_getDiagnosticNumFixIts(self.diag))

            def __getitem__(self, key):
                range = SourceRange()
                value = _clang_getDiagnosticFixIt(self.diag, key, byref(range))
                if len(value) == 0:
                    raise IndexError

                return FixIt(range, value)

        return FixItIterator(self)

    def __repr__(self):
        return "<Diagnostic severity %r, location %r, spelling %r>" % (
            self.severity, self.location, self.spelling)

    def from_param(self):
      return self.ptr

class FixIt(object):
    """
    A FixIt represents a transformation to be applied to the source to
    "fix-it". The fix-it shouldbe applied by replacing the given source range
    with the given value.
    """

    def __init__(self, range, value):
        self.range = range
        self.value = value

    def __repr__(self):
        return "<FixIt range %r, value %r>" % (self.range, self.value)

### Cursor Kinds ###

class CursorKind(object):
    """
    A CursorKind describes the kind of entity that a cursor points to.
    """

    # The unique kind objects, indexed by id.
    _kinds = []
    _name_map = None

    def __init__(self, value):
        if value >= len(CursorKind._kinds):
            CursorKind._kinds += [None] * (value - len(CursorKind._kinds) + 1)
        if CursorKind._kinds[value] is not None:
            raise ValueError,'CursorKind already loaded'
        self.value = value
        CursorKind._kinds[value] = self
        CursorKind._name_map = None

    def from_param(self):
        return self.value

    def __eq__(self, other):
        return self.value == other.value

    def __ne__(self, other):
        return self.value != other.value

    @property
    def name(self):
        """Get the enumeration name of this cursor kind."""
        if self._name_map is None:
            self._name_map = {}
            for key,value in CursorKind.__dict__.items():
                if isinstance(value,CursorKind):
                    self._name_map[value] = key
        return self._name_map[self]

    @staticmethod
    def from_id(id):
        if id >= len(CursorKind._kinds) or CursorKind._kinds[id] is None:
            raise ValueError,'Unknown cursor kind'
        return CursorKind._kinds[id]

    @staticmethod
    def get_all_kinds():
        """Return all CursorKind enumeration instances."""
        return filter(None, CursorKind._kinds)

    def is_declaration(self):
        """Test if this is a declaration kind."""
        return CursorKind_is_decl(self)

    def is_reference(self):
        """Test if this is a reference kind."""
        return CursorKind_is_ref(self)

    def is_expression(self):
        """Test if this is an expression kind."""
        return CursorKind_is_expr(self)

    def is_statement(self):
        """Test if this is a statement kind."""
        return CursorKind_is_stmt(self)

    #def is_attribute(self):
    #    """Test if this is an attribute kind."""
    #    return CursorKind_is_attribute(self)

    def is_invalid(self):
        """Test if this is an invalid kind."""
        return CursorKind_is_inv(self)

    def __repr__(self):
        return 'CursorKind.%s' % (self.name,)

# FIXME: Is there a nicer way to expose this enumeration? We could potentially
# represent the nested structure, or even build a class hierarchy. The main
# things we want for sure are (a) simple external access to kinds, (b) a place
# to hang a description and name, (c) easy to keep in sync with Index.h.

###
# Declaration Kinds

# A declaration whose specific kind is not exposed via this interface.
#
# Unexposed declarations have the same operations as any other kind of
# declaration; one can extract their location information, spelling, find their
# definitions, etc. However, the specific kind of the declaration is not
# reported.
CursorKind.UNEXPOSED_DECL = CursorKind(1)

# A C or C++ struct.
CursorKind.STRUCT_DECL = CursorKind(2)

# A C or C++ union.
CursorKind.UNION_DECL = CursorKind(3)

# A C++ class.
CursorKind.CLASS_DECL = CursorKind(4)

# An enumeration.
CursorKind.ENUM_DECL = CursorKind(5)

# A field (in C) or non-static data member (in C++) in a struct, union, or C++
# class.
CursorKind.FIELD_DECL = CursorKind(6)

# An enumerator constant.
CursorKind.ENUM_CONSTANT_DECL = CursorKind(7)

# A function.
CursorKind.FUNCTION_DECL = CursorKind(8)

# A variable.
CursorKind.VAR_DECL = CursorKind(9)

# A function or method parameter.
CursorKind.PARM_DECL = CursorKind(10)

# An Objective-C @interface.
CursorKind.OBJC_INTERFACE_DECL = CursorKind(11)

# An Objective-C @interface for a category.
CursorKind.OBJC_CATEGORY_DECL = CursorKind(12)

# An Objective-C @protocol declaration.
CursorKind.OBJC_PROTOCOL_DECL = CursorKind(13)

# An Objective-C @property declaration.
CursorKind.OBJC_PROPERTY_DECL = CursorKind(14)

# An Objective-C instance variable.
CursorKind.OBJC_IVAR_DECL = CursorKind(15)

# An Objective-C instance method.
CursorKind.OBJC_INSTANCE_METHOD_DECL = CursorKind(16)

# An Objective-C class method.
CursorKind.OBJC_CLASS_METHOD_DECL = CursorKind(17)

# An Objective-C @implementation.
CursorKind.OBJC_IMPLEMENTATION_DECL = CursorKind(18)

# An Objective-C @implementation for a category.
CursorKind.OBJC_CATEGORY_IMPL_DECL = CursorKind(19)

# A typedef.
CursorKind.TYPEDEF_DECL = CursorKind(20)

# A C++ class method.
CursorKind.CXX_METHOD = CursorKind(21)

# A C++ namespace.
CursorKind.NAMESPACE = CursorKind(22)

# A linkage specification, e.g. 'extern "C"'.
CursorKind.LINKAGE_SPEC = CursorKind(23)

# A C++ constructor.
CursorKind.CONSTRUCTOR = CursorKind(24)

# A C++ destructor.
CursorKind.DESTRUCTOR = CursorKind(25)

# A C++ conversion function.
CursorKind.CONVERSION_FUNCTION = CursorKind(26)

# A C++ template type parameter
CursorKind.TEMPLATE_TYPE_PARAMETER = CursorKind(27)

# A C++ non-type template paramater.
CursorKind.TEMPLATE_NON_TYPE_PARAMETER = CursorKind(28)

# A C++ template template parameter.
CursorKind.TEMPLATE_TEMPLATE_PARAMTER = CursorKind(29)

# A C++ function template.
CursorKind.FUNCTION_TEMPLATE = CursorKind(30)

# A C++ class template.
CursorKind.CLASS_TEMPLATE = CursorKind(31)

# A C++ class template partial specialization.
CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION = CursorKind(32)

# A C++ namespace alias declaration.
CursorKind.NAMESPACE_ALIAS = CursorKind(33)

# A C++ using directive
CursorKind.USING_DIRECTIVE = CursorKind(34)

# A C++ using declaration
CursorKind.USING_DECLARATION = CursorKind(35)

# A Type alias decl.
CursorKind.TYPE_ALIAS_DECL = CursorKind(36)

# A Objective-C synthesize decl
CursorKind.OBJC_SYNTHESIZE_DECL = CursorKind(37)

# A Objective-C dynamic decl
CursorKind.OBJC_DYNAMIC_DECL = CursorKind(38)

# A C++ access specifier decl.
CursorKind.CXX_ACCESS_SPEC_DECL = CursorKind(39)


###
# Reference Kinds

CursorKind.OBJC_SUPER_CLASS_REF = CursorKind(40)
CursorKind.OBJC_PROTOCOL_REF = CursorKind(41)
CursorKind.OBJC_CLASS_REF = CursorKind(42)

# A reference to a type declaration.
#
# A type reference occurs anywhere where a type is named but not
# declared. For example, given:
#   typedef unsigned size_type;
#   size_type size;
#
# The typedef is a declaration of size_type (CXCursor_TypedefDecl),
# while the type of the variable "size" is referenced. The cursor
# referenced by the type of size is the typedef for size_type.
CursorKind.TYPE_REF = CursorKind(43)
CursorKind.CXX_BASE_SPECIFIER = CursorKind(44)

# A reference to a class template, function template, template
# template parameter, or class template partial specialization.
CursorKind.TEMPLATE_REF = CursorKind(45)

# A reference to a namespace or namepsace alias.
CursorKind.NAMESPACE_REF = CursorKind(46)

# A reference to a member of a struct, union, or class that occurs in
# some non-expression context, e.g., a designated initializer.
CursorKind.MEMBER_REF = CursorKind(47)

# A reference to a labeled statement.
CursorKind.LABEL_REF = CursorKind(48)

# A reference toa a set of overloaded functions or function templates
# that has not yet been resolved to a specific function or function template.
CursorKind.OVERLOADED_DECL_REF = CursorKind(49)

###
# Invalid/Error Kinds

CursorKind.INVALID_FILE = CursorKind(70)
CursorKind.NO_DECL_FOUND = CursorKind(71)
CursorKind.NOT_IMPLEMENTED = CursorKind(72)
CursorKind.INVALID_CODE = CursorKind(73)

###
# Expression Kinds

# An expression whose specific kind is not exposed via this interface.
#
# Unexposed expressions have the same operations as any other kind of
# expression; one can extract their location information, spelling, children,
# etc. However, the specific kind of the expression is not reported.
CursorKind.UNEXPOSED_EXPR = CursorKind(100)

# An expression that refers to some value declaration, such as a function,
# varible, or enumerator.
CursorKind.DECL_REF_EXPR = CursorKind(101)

# An expression that refers to a member of a struct, union, class, Objective-C
# class, etc.
CursorKind.MEMBER_REF_EXPR = CursorKind(102)

# An expression that calls a function.
CursorKind.CALL_EXPR = CursorKind(103)

# An expression that sends a message to an Objective-C object or class.
CursorKind.OBJC_MESSAGE_EXPR = CursorKind(104)

# An expression that represents a block literal.
CursorKind.BLOCK_EXPR = CursorKind(105)

# An integer literal.
CursorKind.INTEGER_LITERAL = CursorKind(106)

# A floating point number literal.
CursorKind.FLOATING_LITERAL = CursorKind(107)

# An imaginary number literal.
CursorKind.IMAGINARY_LITERAL = CursorKind(108)

# A string literal.
CursorKind.STRING_LITERAL = CursorKind(109)

# A character literal.
CursorKind.CHARACTER_LITERAL = CursorKind(110)

# A parenthesized expression, e.g. "(1)".
#
# This AST node is only formed if full location information is requested.
CursorKind.PAREN_EXPR = CursorKind(111)

# This represents the unary-expression's (except sizeof and
# alignof).
CursorKind.UNARY_OPERATOR = CursorKind(112)

# [C99 6.5.2.1] Array Subscripting.
CursorKind.ARRAY_SUBSCRIPT_EXPR = CursorKind(113)

# A builtin binary operation expression such as "x + y" or
# "x <= y".
CursorKind.BINARY_OPERATOR = CursorKind(114)

# Compound assignment such as "+=".
CursorKind.COMPOUND_ASSIGNMENT_OPERATOR = CursorKind(115)

# The ?: ternary operator.
CursorKind.CONDITONAL_OPERATOR = CursorKind(116)

# An explicit cast in C (C99 6.5.4) or a C-style cast in C++
# (C++ [expr.cast]), which uses the syntax (Type)expr.
#
# For example: (int)f.
CursorKind.CSTYLE_CAST_EXPR = CursorKind(117)

# [C99 6.5.2.5]
CursorKind.COMPOUND_LITERAL_EXPR = CursorKind(118)

# Describes an C or C++ initializer list.
CursorKind.INIT_LIST_EXPR = CursorKind(119)

# The GNU address of label extension, representing &&label.
CursorKind.ADDR_LABEL_EXPR = CursorKind(120)

# This is the GNU Statement Expression extension: ({int X=4; X;})
CursorKind.StmtExpr = CursorKind(121)

# Represents a C1X generic selection.
CursorKind.GENERIC_SELECTION_EXPR = CursorKind(122)

# Implements the GNU __null extension, which is a name for a null
# pointer constant that has integral type (e.g., int or long) and is the same
# size and alignment as a pointer.
#
# The __null extension is typically only used by system headers, which define
# NULL as __null in C++ rather than using 0 (which is an integer that may not
# match the size of a pointer).
CursorKind.GNU_NULL_EXPR = CursorKind(123)

# C++'s static_cast<> expression.
CursorKind.CXX_STATIC_CAST_EXPR = CursorKind(124)

# C++'s dynamic_cast<> expression.
CursorKind.CXX_DYNAMIC_CAST_EXPR = CursorKind(125)

# C++'s reinterpret_cast<> expression.
CursorKind.CXX_REINTERPRET_CAST_EXPR = CursorKind(126)

# C++'s const_cast<> expression.
CursorKind.CXX_CONST_CAST_EXPR = CursorKind(127)

# Represents an explicit C++ type conversion that uses "functional"
# notion (C++ [expr.type.conv]).
#
# Example:
# \code
#   x = int(0.5);
# \endcode
CursorKind.CXX_FUNCTIONAL_CAST_EXPR = CursorKind(128)

# A C++ typeid expression (C++ [expr.typeid]).
CursorKind.CXX_TYPEID_EXPR = CursorKind(129)

# [C++ 2.13.5] C++ Boolean Literal.
CursorKind.CXX_BOOL_LITERAL_EXPR = CursorKind(130)

# [C++0x 2.14.7] C++ Pointer Literal.
CursorKind.CXX_NULL_PTR_LITERAL_EXPR = CursorKind(131)

# Represents the "this" expression in C++
CursorKind.CXX_THIS_EXPR = CursorKind(132)

# [C++ 15] C++ Throw Expression.
#
# This handles 'throw' and 'throw' assignment-expression. When
# assignment-expression isn't present, Op will be null.
CursorKind.CXX_THROW_EXPR = CursorKind(133)

# A new expression for memory allocation and constructor calls, e.g:
# "new CXXNewExpr(foo)".
CursorKind.CXX_NEW_EXPR = CursorKind(134)

# A delete expression for memory deallocation and destructor calls,
# e.g. "delete[] pArray".
CursorKind.CXX_DELETE_EXPR = CursorKind(135)

# Represents a unary expression.
CursorKind.CXX_UNARY_EXPR = CursorKind(136)

# ObjCStringLiteral, used for Objective-C string literals i.e. "foo".
CursorKind.OBJC_STRING_LITERAL = CursorKind(137)

# ObjCEncodeExpr, used for in Objective-C.
CursorKind.OBJC_ENCODE_EXPR = CursorKind(138)

# ObjCSelectorExpr used for in Objective-C.
CursorKind.OBJC_SELECTOR_EXPR = CursorKind(139)

# Objective-C's protocol expression.
CursorKind.OBJC_PROTOCOL_EXPR = CursorKind(140)

# An Objective-C "bridged" cast expression, which casts between
# Objective-C pointers and C pointers, transferring ownership in the process.
#
# \code
#   NSString *str = (__bridge_transfer NSString *)CFCreateString();
# \endcode
CursorKind.OBJC_BRIDGE_CAST_EXPR = CursorKind(141)

# Represents a C++0x pack expansion that produces a sequence of
# expressions.
#
# A pack expansion expression contains a pattern (which itself is an
# expression) followed by an ellipsis. For example:
CursorKind.PACK_EXPANSION_EXPR = CursorKind(142)

# Represents an expression that computes the length of a parameter
# pack.
CursorKind.SIZE_OF_PACK_EXPR = CursorKind(143)

# A statement whose specific kind is not exposed via this interface.
#
# Unexposed statements have the same operations as any other kind of statement;
# one can extract their location information, spelling, children, etc. However,
# the specific kind of the statement is not reported.
CursorKind.UNEXPOSED_STMT = CursorKind(200)

# A labelled statement in a function.
CursorKind.LABEL_STMT = CursorKind(201)

# A compound statement
CursorKind.COMPOUND_STMT = CursorKind(202)

# A case statement.
CursorKind.CASE_STMT = CursorKind(203)

# A default statement.
CursorKind.DEFAULT_STMT = CursorKind(204)

# An if statement.
CursorKind.IF_STMT = CursorKind(205)

# A switch statement.
CursorKind.SWITCH_STMT = CursorKind(206)

# A while statement.
CursorKind.WHILE_STMT = CursorKind(207)

# A do statement.
CursorKind.DO_STMT = CursorKind(208)

# A for statement.
CursorKind.FOR_STMT = CursorKind(209)

# A goto statement.
CursorKind.GOTO_STMT = CursorKind(210)

# An indirect goto statement.
CursorKind.INDIRECT_GOTO_STMT = CursorKind(211)

# A continue statement.
CursorKind.CONTINUE_STMT = CursorKind(212)

# A break statement.
CursorKind.BREAK_STMT = CursorKind(213)

# A return statement.
CursorKind.RETURN_STMT = CursorKind(214)

# A GNU-style inline assembler statement.
CursorKind.ASM_STMT = CursorKind(215)

# Objective-C's overall @try-@catch-@finally statement.
CursorKind.OBJC_AT_TRY_STMT = CursorKind(216)

# Objective-C's @catch statement.
CursorKind.OBJC_AT_CATCH_STMT = CursorKind(217)

# Objective-C's @finally statement.
CursorKind.OBJC_AT_FINALLY_STMT = CursorKind(218)

# Objective-C's @throw statement.
CursorKind.OBJC_AT_THROW_STMT = CursorKind(219)

# Objective-C's @synchronized statement.
CursorKind.OBJC_AT_SYNCHRONIZED_STMT = CursorKind(220)

# Objective-C's autorealease pool statement.
CursorKind.OBJC_AUTORELEASE_POOL_STMT = CursorKind(221)

# Objective-C's for collection statement.
CursorKind.OBJC_FOR_COLLECTION_STMT = CursorKind(222)

# C++'s catch statement.
CursorKind.CXX_CATCH_STMT = CursorKind(223)

# C++'s try statement.
CursorKind.CXX_TRY_STMT = CursorKind(224)

# C++'s for (* : *) statement.
CursorKind.CXX_FOR_RANGE_STMT = CursorKind(225)

# Windows Structured Exception Handling's try statement.
CursorKind.SEH_TRY_STMT = CursorKind(226)

# Windows Structured Exception Handling's except statement.
CursorKind.SEH_EXCEPT_STMT = CursorKind(227)

# Windows Structured Exception Handling's finally statement.
CursorKind.SEH_FINALLY_STMT = CursorKind(228)

# The null statement.
CursorKind.NULL_STMT = CursorKind(230)

# Adaptor class for mixing declarations with statements and expressions.
CursorKind.DECL_STMT = CursorKind(231)

###
# Other Kinds

# Cursor that represents the translation unit itself.
#
# The translation unit cursor exists primarily to act as the root cursor for
# traversing the contents of a translation unit.
CursorKind.TRANSLATION_UNIT = CursorKind(300)

###
# Attributes

# An attribute whoe specific kind is note exposed via this interface
CursorKind.UNEXPOSED_ATTR = CursorKind(400)

CursorKind.IB_ACTION_ATTR = CursorKind(401)
CursorKind.IB_OUTLET_ATTR = CursorKind(402)
CursorKind.IB_OUTLET_COLLECTION_ATTR = CursorKind(403)

###
# Preprocessing
CursorKind.PREPROCESSING_DIRECTIVE = CursorKind(500)
CursorKind.MACRO_DEFINITION = CursorKind(501)
CursorKind.MACRO_INSTANTIATION = CursorKind(502)
CursorKind.INCLUSION_DIRECTIVE = CursorKind(503)


class CXXAccessSpecifier:
    def __init__(self, name, kind):
        self.name = name
        self.kind = kind

    def __str__(self):
        return self.name

    def is_public(self):
        return self.kind == 1

    def is_protected(self):
        return self.kind == 2

    def is_private(self):
        return self.kind == 3

_cxx_access_specifiers = {
       0: CXXAccessSpecifier("CX_CXXInvalidAccessSpecifier", 0),
       1: CXXAccessSpecifier("CX_CXXPublic", 1),
       2: CXXAccessSpecifier("CX_CXXProtected", 2),
       3: CXXAccessSpecifier("CX_CXXPrivate", 3)
}

CXXAccessSpecifier.PUBLIC = 1
CXXAccessSpecifier.PROTECTED = 2
CXXAccessSpecifier.PRIVATE = 3
### Cursors ###

class Cursor(Structure):
    """
    The Cursor class represents a reference to an element within the AST. It
    acts as a kind of iterator.
    """
    _fields_ = [("_kind_id", c_int), ("xdata", c_int), ("data", c_void_p * 3)]

    def __eq__(self, other):
        return Cursor_eq(self, other)

    def __ne__(self, other):
        return not Cursor_eq(self, other)

    def is_definition(self):
        """
        Returns true if the declaration pointed at by the cursor is also a
        definition of that entity.
        """
        return Cursor_is_def(self)

    @staticmethod
    def get(tu, filename, row, col):
        obj = _clang_getFile(tu, filename)
        if not obj:
            return None
        f = File(obj)
        sl = _clang_getLocation(tu, f, row, col)
        return Cursor_get(tu, sl)

    def get_completion_string(self):
        return CompletionString(_clang_getCursorCompletionString(self))

    def get_included_file(self):
        obj = _clang_getIncludedFile(self)
        if not obj:
            return None
        return File(obj)

    def get_overridden(self):
        class OverriddenIter:
            def __init__(self, cursor):
                a = Cursor()
                self.obj = pointer(a)
                self.num = c_int(0)
                Cursor_getOverridden(cursor, byref(self.obj), byref(self.num))

            def __del__(self):
                if self.num.value != 0:
                    Cursor_disposeOverridden(self.obj)

            def __len__(self):
                return self.num.value

            def __getitem__(self, key):
                if key >= self.num:
                    raise IndexError
                return self.obj[key]
        return OverriddenIter(self)

    def get_definition(self):
        """
        If the cursor is a reference to a declaration or a declaration of
        some entity, return a cursor that points to the definition of that
        entity.
        """
        # TODO: Should probably check that this is either a reference or
        # declaration prior to issuing the lookup.
        return Cursor_def(self)

    def get_reference(self):
        return Cursor_ref(self)

    def get_semantic_parent(self):
        return Cursor_semanticParent(self)

    def get_lexical_parent(self):
        return Cursor_lexicalParent(self)

    def get_canonical_cursor(self):
        return Cursor_get_canonical(self)

    def get_linkage(self):
        return Cursor_get_linkage(self)

    def get_specialized_cursor_template(self):
        return _clang_getSpecializedCursorTemplate(self)

    def get_usr(self):
        """Return the Unified Symbol Resultion (USR) for the entity referenced
        by the given cursor (or None).

        A Unified Symbol Resolution (USR) is a string that identifies a
        particular entity (function, class, variable, etc.) within a
        program. USRs can be compared across translation units to determine,
        e.g., when references in one translation refer to an entity defined in
        another translation unit."""
        return Cursor_usr(self)

    def get_cxx_access_specifier(self):
        return _cxx_access_specifiers[_clang_getCXXAccessSpecifier(self)]

    def get_cxxmethod_is_static(self):
        return _clang_CXXMethod_isStatic(self)

    def get_referenced_name_range(self):
        return _clang_getCursorReferenceNameRange(self, 2, 0)

    @property
    def availability(self):
        return _clang_getCursorAvailability(self)

    @property
    def kind(self):
        """Return the kind of this cursor."""
        if not hasattr(self, '_kind'):
            self._kind = CursorKind.from_id(self._kind_id)
        return self._kind

    @property
    def spelling(self):
        """Return the spelling of the entity pointed at by the cursor."""
        if not self.kind.is_declaration():
            # FIXME: clang_getCursorSpelling should be fixed to not assert on
            # this, for consistency with clang_getCursorUSR.
            return None
        if not hasattr(self, '_spelling'):
            self._spelling = Cursor_spelling(self)
        return self._spelling

    @property
    def displayname(self):
        """
        Return the display name for the entity referenced by this cursor.

        The display name contains extra information that helps identify the cursor,
        such as the parameters of a function or template or the arguments of a
        class template specialization.
        """
        if not hasattr(self, '_displayname'):
            self._displayname = Cursor_displayname(self)
        return self._displayname

    @property
    def location(self):
        """
        Return the source location (the starting character) of the entity
        pointed at by the cursor.
        """
        if not hasattr(self, '_loc'):
            self._loc = Cursor_loc(self)
        return self._loc

    @property
    def extent(self):
        """
        Return the source range (the range of text) occupied by the entity
        pointed at by the cursor.
        """
        if not hasattr(self, '_extent'):
            self._extent = Cursor_extent(self)
        return self._extent

    @property
    def type(self):
        """
        Retrieve the type (if any) of of the entity pointed at by the
        cursor.
        """
        if not hasattr(self, '_type'):
            self._type = Cursor_type(self)
        return self._type

    @property
    def result_type(self):
        """
        Retrieve the result type (if any) of the entity pointed at by the
        cursor.
        """
        if not hasattr(self, '_resulttype'):
            self._resulttype = _clang_getCursorResultType(self)
        return self._resulttype

    @property
    def translation_unit(self):
        if not hasattr(self, '_translation_unit'):
            self._translation_unit = TranslationUnit(Cursor_getTranslationUnit(self), False)
        return self._translation_unit

    def get_children(self):
        """Return an iterator for accessing the children of this cursor."""

        # FIXME: Expose iteration from CIndex, PR6125.
        def visitor(child, parent, children):
            # FIXME: Document this assertion in API.
            # FIXME: There should just be an isNull method.
            if isWin64:
                _child = Cursor()
                #_fields_ = [("_kind_id", c_int), ("xdata", c_int), ("data", c_void_p * 3)]

                _child._kind_id = child[0]._kind_id #dealing with pointers on Win64
                _child.xdata = child[0].xdata
                _child.data = child[0].data
                children.append(_child)
            else:
                assert child != Cursor_null()
                children.append(child)
            return 1 # continue
        children = []
        Cursor_visit(self, Cursor_visit_callback(visitor), children)
        return children

    def get_returned_pointer_level(self, curr=0):
        ret = 0
        type = None

        if not self.result_type.kind.is_invalid():
            type = self.result_type
        else:
            type = self.type
        while not type is None:
            if type.kind == TypeKind.POINTER:
                type = type.get_pointee()
            elif type.kind == TypeKind.CONSTANTARRAY:
                type = type.get_array_element_type()
            elif type.kind == TypeKind.TYPEDEF:
                children = self.get_children()
                if len(children) == 1 and children[0].kind == CursorKind.TYPE_REF:
                    ref = children[0].get_reference()
                    return ret + ref.get_returned_pointer_level()

                if self.kind == CursorKind.TYPEDEF_DECL:
                    for child in children:
                        if child.kind == CursorKind.INTEGER_LITERAL:
                            ret += 1
                break
            else:
                break
            ret += 1

        return ret

    def get_resolved_cursor(self):
        #print "get_type"
        if self.kind == CursorKind.OBJC_INTERFACE_DECL:
            return self
        if self.kind == CursorKind.STRUCT_DECL or \
                self.kind == CursorKind.CLASS_DECL or \
                self.kind == CursorKind.CLASS_TEMPLATE:
            ret = self.get_definition()
            if ret is None:
                ret = self
            return ret
        if self.kind == CursorKind.TYPEDEF_DECL:
            children = self.get_children()
            simple = True
            first = 0
            for child in children:
                if child.kind != CursorKind.NAMESPACE_REF:
                    break
                first += 1

            for child in children[first+1:]:
                if child.kind != CursorKind.INTEGER_LITERAL:
                    simple = False
                    break
            if simple and len(children) > 0:
                return children[first].get_resolved_cursor()
            return self
        elif self.result_type.kind == TypeKind.RECORD:
            return self.get_children()[0].get_resolved_cursor()
        elif self.kind == CursorKind.CLASS_DECL or self.kind == CursorKind.ENUM_DECL or self.kind == CursorKind.CLASS_TEMPLATE:
            return self
        elif self.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
            return self
        elif self.kind.is_reference():
            ref = self.get_reference()
            if ref == self:
                #print "none1"
                return None
            return ref.get_resolved_cursor()
        elif self.kind.is_declaration():
            #print "decl: %s, %s" % (self.spelling, self.kind)
            for child in self.get_children():
                #print "%s, %s, %s, %s" % (child.kind, child.spelling, child.type.kind, child.result_type.kind)
                if child.kind == CursorKind.TYPE_REF:
                    c = child.get_reference()
                    #print "will return this type: "
                    #self.dump(c)
                    if c == child:
                        #print "none3"
                        return None
                    return c.get_resolved_cursor()
                elif child.kind == CursorKind.ENUM_DECL:
                    return child
                elif child.kind == CursorKind.TEMPLATE_REF:
                    return self
        #if self.kind == CursorKind.TYPE_REF:
        #    return self.get_reference()

        #if self.kind == CursorKind.TYPEDEF_DECL:
        #    print "here"
        #    self.dump_cursor(self)
        # return self.get_type_from_:cursor(self, self.get_reference())
        if self.result_type.kind == TypeKind.POINTER or self.result_type.kind == TypeKind.LVALUEREFERENCE or self.result_type.kind == TypeKind.RVALUEREFERENCE:
            return self.result_type.get_pointee().get_declaration()

        # print "none2"
        # self.dump_self()
        # print "self dumped"
        return self

    def dump_self(self):
        if self is None or self.kind.is_invalid():
            print "cursor: None"
            return
        print "cursor: %s, %s, %s, %s, %s, %s" % (self.kind, self.type.kind, self.result_type.kind, self.spelling, self.displayname, self.get_usr())
        source = "<unknown>" if self.location.file is None else self.location.file.name
        print "defined at: %s, %d, %d" % (source, self.location.line, self.location.column)

    def dump(self, once=True):
        indent = "" if once else "    "
        print "%s this: %s, %s, %s, %s, %s, %s, %s" % (indent, self.kind, self.spelling, self.displayname, self.type.kind, self.result_type.kind, self.get_usr(), self.location)
        children = self.get_children()
        for i in range(len(children)):
            child = children[i]
            print "%s    %d: %s, %s, %s, %s, %s, %s" % (indent, i, child.kind, child.spelling, child.displayname, child.type.kind, child.result_type.kind, child.get_usr())
            if child.kind == CursorKind.CXX_ACCESS_SPEC_DECL:
                print "    %s access: %s" % (indent, child.get_cxx_access_specifier())
            if child.result_type.kind == TypeKind.POINTER:
                pointee = child.result_type.get_pointee()
                c3 = pointee.get_declaration()
                if not c3 is None and not c3.kind.is_invalid():
                    print "    %s dumping pointee" % indent
                    c3.dump_self()
                else:
                    print "c3 == null"
            if child.kind.is_reference() and child.kind != CursorKind.NAMESPACE_REF and once:
                child.get_reference().dump(False)
            elif child.kind == CursorKind.COMPOUND_STMT and once:
                child.dump(False)

    def get_returned_cursor(self):
        ret = None
        if self.kind == CursorKind.FUNCTION_DECL or \
                    self.kind == CursorKind.FIELD_DECL or \
                    self.kind == CursorKind.CXX_METHOD or \
                    self.kind == CursorKind.OBJC_INSTANCE_METHOD_DECL or \
                    self.kind == CursorKind.OBJC_CLASS_METHOD_DECL or \
                    self.kind == CursorKind.OBJC_PROPERTY_DECL or \
                    self.kind == CursorKind.OBJC_IVAR_DECL or \
                    self.kind == CursorKind.VAR_DECL or \
                    self.kind == CursorKind.PARM_DECL:
            children = self.get_children()
            if len(children) > 0:
                c = children[0]
                i = 0
                while c.kind == CursorKind.NAMESPACE_REF and i+1 < len(children):
                    c = children[i]
                    i += 1

                #if c.kind == CursorKind.TEMPLATE_REF:
                #    return self
                #el
                if c.kind.is_reference():
                    i = 0
                    while i < len(children):
                        c = children[i]
                        if c.kind != CursorKind.NAMESPACE_REF:
                            reference = c.get_reference()
                            definition = reference.get_definition()
                            if definition is None or reference.kind == CursorKind.OBJC_INTERFACE_DECL:
                                definition = reference

                            if definition is None or definition == c:
                                return None
                            return definition.get_resolved_cursor()
                        i += 1
                    return None
                elif c.kind == CursorKind.STRUCT_DECL:
                    return c
                else:
                    return None
            else:
                #print "none4"
                return None
        # if self.kind.is_reference():
        #     ref = self.get_reference()
        #     if self == ref:
        #         return None
        #     return ref.get_resolved_cursor()
        # TODO: cleanup
        #print "getting returned cursor of %s, %s, %s, %s" % (self.kind, self.spelling, self.type.kind, self.result_type.kind)
        if self.kind.is_declaration():
            ret = self #.get_resolved_cursor()
        if self.result_type.kind == TypeKind.RECORD:
            ret = self.get_children()[0]
        if self.result_type.kind == TypeKind.POINTER or \
                    self.result_type.kind == TypeKind.LVALUEREFERENCE or \
                    self.result_type.kind == TypeKind.RVALUEREFERENCE:

            pointee = self.result_type.get_pointee()
            #print "pointee kind: %s" % (pointee.kind)
            ret = pointee.get_declaration()
            if ret is None or ret.kind.is_invalid():
                #ret = pointee.get_canonical().get_declaration()
                ret = self.result_type.get_result().get_declaration()

        #ret.dump_self()
        if not ret is None and not ret.kind.is_invalid():
            #ret.dump()
            return ret.get_resolved_cursor()
        #print "none5"
        return None

    def get_member(self, membername, function):
        #print "want to get the cursor for: %s->%s%s" % (self.spelling, membername, "()" if function else "")
        for child in self.get_children():
            if function and (child.kind == CursorKind.CXX_METHOD or child.kind == CursorKind.OBJC_INSTANCE_METHOD_DECL) and child.spelling == membername:
                return child
            elif not function and (child.kind == CursorKind.FIELD_DECL or child.kind == CursorKind.VAR_DECL or child.kind == CursorKind.OBJC_IVAR_DECL) and child.spelling == membername:
                return child
            # elif child.spelling == membername:
            #     print "unhandled kind: %s" % child.kind
        if self.kind == CursorKind.OBJC_INTERFACE_DECL:
            for child in self.get_children():
                if child.kind == CursorKind.OBJC_INSTANCE_METHOD_DECL and child.spelling == membername:
                    ret = True
                    for c2 in child.get_children():
                        if c2.kind == CursorKind.PARM_DECL:
                            ret = False
                            break
                    if ret:
                        return child

        # Not found in this class, try base class
        for child in self.get_children():
            if child.kind == CursorKind.CXX_BASE_SPECIFIER:
                ret = child.get_reference().get_member(membername, function)
                if ret:
                    return ret
        return None

    @staticmethod
    def from_result(res, fn, args):
        assert isinstance(res, Cursor)
        # FIXME: There should just be an isNull method.
        if res == Cursor_null():
            return None
        return res

### Type Kinds ###

class TypeKind(object):
    """
    Describes the kind of type.
    """

    # The unique kind objects, indexed by id.
    _kinds = []
    _name_map = None

    def __init__(self, value):
        if value >= len(TypeKind._kinds):
            TypeKind._kinds += [None] * (value - len(TypeKind._kinds) + 1)
        if TypeKind._kinds[value] is not None:
            raise ValueError,'TypeKind already loaded'
        self.value = value
        TypeKind._kinds[value] = self
        TypeKind._name_map = None

    def from_param(self):
        return self.value

    @property
    def name(self):
        """Get the enumeration name of this cursor kind."""
        if self._name_map is None:
            self._name_map = {}
            for key,value in TypeKind.__dict__.items():
                if isinstance(value,TypeKind):
                    self._name_map[value] = key
        return self._name_map[self]

    @staticmethod
    def from_id(id):
        if id >= len(TypeKind._kinds) or TypeKind._kinds[id] is None:
            raise ValueError,'Unknown cursor kind'
        return TypeKind._kinds[id]

    def __repr__(self):
        return 'TypeKind.%s' % (self.name,)

    def is_invalid(self):
        return self.value == 0



TypeKind.INVALID = TypeKind(0)
TypeKind.UNEXPOSED = TypeKind(1)
TypeKind.VOID = TypeKind(2)
TypeKind.BOOL = TypeKind(3)
TypeKind.CHAR_U = TypeKind(4)
TypeKind.UCHAR = TypeKind(5)
TypeKind.CHAR16 = TypeKind(6)
TypeKind.CHAR32 = TypeKind(7)
TypeKind.USHORT = TypeKind(8)
TypeKind.UINT = TypeKind(9)
TypeKind.ULONG = TypeKind(10)
TypeKind.ULONGLONG = TypeKind(11)
TypeKind.UINT128 = TypeKind(12)
TypeKind.CHAR_S = TypeKind(13)
TypeKind.SCHAR = TypeKind(14)
TypeKind.WCHAR = TypeKind(15)
TypeKind.SHORT = TypeKind(16)
TypeKind.INT = TypeKind(17)
TypeKind.LONG = TypeKind(18)
TypeKind.LONGLONG = TypeKind(19)
TypeKind.INT128 = TypeKind(20)
TypeKind.FLOAT = TypeKind(21)
TypeKind.DOUBLE = TypeKind(22)
TypeKind.LONGDOUBLE = TypeKind(23)
TypeKind.NULLPTR = TypeKind(24)
TypeKind.OVERLOAD = TypeKind(25)
TypeKind.DEPENDENT = TypeKind(26)
TypeKind.OBJCID = TypeKind(27)
TypeKind.OBJCCLASS = TypeKind(28)
TypeKind.OBJCSEL = TypeKind(29)
TypeKind.COMPLEX = TypeKind(100)
TypeKind.POINTER = TypeKind(101)
TypeKind.BLOCKPOINTER = TypeKind(102)
TypeKind.LVALUEREFERENCE = TypeKind(103)
TypeKind.RVALUEREFERENCE = TypeKind(104)
TypeKind.RECORD = TypeKind(105)
TypeKind.ENUM = TypeKind(106)
TypeKind.TYPEDEF = TypeKind(107)
TypeKind.OBJCINTERFACE = TypeKind(108)
TypeKind.OBJCOBJECTPOINTER = TypeKind(109)
TypeKind.FUNCTIONNOPROTO = TypeKind(110)
TypeKind.FUNCTIONPROTO = TypeKind(111)
TypeKind.CONSTANTARRAY = TypeKind(112)

class Type(Structure):
    """
    The type of an element in the abstract syntax tree.
    """
    _fields_ = [("_kind_id", c_int), ("data", c_void_p * 2)]

    @property
    def kind(self):
        """Return the kind of this type."""
        return TypeKind.from_id(self._kind_id)

    @staticmethod
    def from_result(res, fn, args):
        assert isinstance(res, Type)
        return res

    def get_canonical(self):
        """
        Return the canonical type for a Type.

        Clang's type system explicitly models typedefs and all the
        ways a specific type can be represented.  The canonical type
        is the underlying type with all the "sugar" removed.  For
        example, if 'T' is a typedef for 'int', the canonical type for
        'T' would be 'int'.
        """
        return Type_get_canonical(self)

    def is_const_qualified(self):
        """
        Determine whether a Type has the "const" qualifier set,
        without looking through typedefs that may have added "const"
        at a different level.
        """
        return Type_is_const_qualified(self)

    def is_volatile_qualified(self):
        """
        Determine whether a Type has the "volatile" qualifier set,
        without looking through typedefs that may have added
        "volatile" at a different level.
        """
        return Type_is_volatile_qualified(self)

    def is_restrict_qualified(self):
        """
        Determine whether a Type has the "restrict" qualifier set,
        without looking through typedefs that may have added
        "restrict" at a different level.
        """
        return Type_is_restrict_qualified(self)

    def get_pointee(self):
        """
        For pointer types, returns the type of the pointee.
        """
        return Type_get_pointee(self)

    def get_declaration(self):
        """
        Return the cursor for the declaration of the given type.
        """
        return Type_get_declaration(self)

    def get_result(self):
        """
        Retrieve the result type associated with a function type.
        """
        return Type_get_result(self)

    def get_array_element_type(self):
        return _clang_getArrayElementType(self)

## CIndex Objects ##

# CIndex objects (derived from ClangObject) are essentially lightweight
# wrappers attached to some underlying object, which is exposed via CIndex as
# a void*.

class ClangObject(object):
    """
    A helper for Clang objects. This class helps act as an intermediary for
    the ctypes library and the Clang CIndex library.
    """
    def __init__(self, obj):
        assert isinstance(obj, c_object_p) and obj
        self.obj = self._as_parameter_ = obj

    def from_param(self):
        return self._as_parameter_


class _CXUnsavedFile(Structure):
    """Helper for passing unsaved file arguments."""
    _fields_ = [("name", c_char_p), ("contents", c_char_p), ('length', c_ulong)]

## Diagnostic Conversion ##

_clang_getNumDiagnostics = lib.clang_getNumDiagnostics
_clang_getNumDiagnostics.argtypes = [c_object_p]
_clang_getNumDiagnostics.restype = c_uint

_clang_getDiagnostic = lib.clang_getDiagnostic
_clang_getDiagnostic.argtypes = [c_object_p, c_uint]
_clang_getDiagnostic.restype = c_object_p

_clang_disposeDiagnostic = lib.clang_disposeDiagnostic
_clang_disposeDiagnostic.argtypes = [Diagnostic]

_clang_getDiagnosticSeverity = lib.clang_getDiagnosticSeverity
_clang_getDiagnosticSeverity.argtypes = [Diagnostic]
_clang_getDiagnosticSeverity.restype = c_int

_clang_getDiagnosticOption = lib.clang_getDiagnosticOption
_clang_getDiagnosticOption.argtypes = [Diagnostic, POINTER(_CXString)]
_clang_getDiagnosticOption.restype = _CXString
_clang_getDiagnosticOption.errcheck = _CXString.from_result

_clang_getDiagnosticLocation = lib.clang_getDiagnosticLocation
_clang_getDiagnosticLocation.argtypes = [Diagnostic]
_clang_getDiagnosticLocation.restype = SourceLocation

_clang_getDiagnosticSpelling = lib.clang_getDiagnosticSpelling
_clang_getDiagnosticSpelling.argtypes = [Diagnostic]
_clang_getDiagnosticSpelling.restype = _CXString
_clang_getDiagnosticSpelling.errcheck = _CXString.from_result

_clang_getDiagnosticNumRanges = lib.clang_getDiagnosticNumRanges
_clang_getDiagnosticNumRanges.argtypes = [Diagnostic]
_clang_getDiagnosticNumRanges.restype = c_uint

_clang_getDiagnosticRange = lib.clang_getDiagnosticRange
_clang_getDiagnosticRange.argtypes = [Diagnostic, c_uint]
_clang_getDiagnosticRange.restype = SourceRange

_clang_getDiagnosticNumFixIts = lib.clang_getDiagnosticNumFixIts
_clang_getDiagnosticNumFixIts.argtypes = [Diagnostic]
_clang_getDiagnosticNumFixIts.restype = c_uint

_clang_getDiagnosticFixIt = lib.clang_getDiagnosticFixIt
_clang_getDiagnosticFixIt.argtypes = [Diagnostic, c_uint, POINTER(SourceRange)]
_clang_getDiagnosticFixIt.restype = _CXString
_clang_getDiagnosticFixIt.errcheck = _CXString.from_result

###

class CompletionChunk:
    class Kind:
        def __init__(self, name):
            self.name = name

        def __str__(self):
            return self.name

        def __repr__(self):
            return "<ChunkKind: %s>" % self

    def __init__(self, completionString, key):
        self.cs = completionString
        self.key = key
        self.kind = completionChunkKindMap[_clang_getCompletionChunkKind(self.cs, self.key)]
        self.spelling = _clang_getCompletionChunkText(self.cs, self.key).spelling

    def __repr__(self):
        return "{'" + self.spelling + "', " + str(self.kind) + "}"

    @property
    def string(self):
        res = _clang_getCompletionChunkCompletionString(self.cs, self.key)

        if (res):
          return CompletionString(res)
        else:
          None

    def isKindOptional(self):
      return self.kind == completionChunkKindMap[0]

    def isKindTypedText(self):
      return self.kind == completionChunkKindMap[1]

    def isKindPlaceHolder(self):
      return self.kind == completionChunkKindMap[3]

    def isKindInformative(self):
      return self.kind == completionChunkKindMap[4]

    def isKindResultType(self):
      return self.kind == completionChunkKindMap[15]

    def isKindCurrentParameter(self):
      return self.kind == completionChunkKindMap[5]

completionChunkKindMap = {
            0: CompletionChunk.Kind("Optional"),
            1: CompletionChunk.Kind("TypedText"),
            2: CompletionChunk.Kind("Text"),
            3: CompletionChunk.Kind("Placeholder"),
            4: CompletionChunk.Kind("Informative"),
            5: CompletionChunk.Kind("CurrentParameter"),
            6: CompletionChunk.Kind("LeftParen"),
            7: CompletionChunk.Kind("RightParen"),
            8: CompletionChunk.Kind("LeftBracket"),
            9: CompletionChunk.Kind("RightBracket"),
            10: CompletionChunk.Kind("LeftBrace"),
            11: CompletionChunk.Kind("RightBrace"),
            12: CompletionChunk.Kind("LeftAngle"),
            13: CompletionChunk.Kind("RightAngle"),
            14: CompletionChunk.Kind("Comma"),
            15: CompletionChunk.Kind("ResultType"),
            16: CompletionChunk.Kind("Colon"),
            17: CompletionChunk.Kind("SemiColon"),
            18: CompletionChunk.Kind("Equal"),
            19: CompletionChunk.Kind("HorizontalSpace"),
            20: CompletionChunk.Kind("VerticalSpace")}

class CompletionString(ClangObject):
    class Availability:
        def __init__(self, name):
            self.name = name

        def __str__(self):
            return self.name

        def __repr__(self):
            return "<Availability: %s>" % self

    def __len__(self):
        return _clang_getNumCompletionChunks(self.obj)

    def __getitem__(self, key):
        if len(self) <= key:
            raise IndexError
        return CompletionChunk(self.obj, key)

    @property
    def priority(self):
        return _clang_getCompletionPriority(self.obj)

    @property
    def availability(self):
        res = _clang_getCompletionAvailability(self.obj)
        return availabilityKinds[res]

    def isAvailabilityNotAccessible(self):
        return _clang_getCompletionAvailability(self.obj) == 3

    def __repr__(self):
        return " | ".join([str(a) for a in self]) \
               + " || Priority: " + str(self.priority) \
               + " || Availability: " + str(self.availability)

availabilityKinds = {
            0: CompletionChunk.Kind("Available"),
            1: CompletionChunk.Kind("Deprecated"),
            2: CompletionChunk.Kind("NotAvailable"),
            3: CompletionChunk.Kind("NotAccessible")}

class CodeCompletionResult(Structure):
    _fields_ = [('cursorKind', c_int), ('completionString', c_object_p)]

    def __repr__(self):
        return str(CompletionString(self.completionString))

    @property
    def kind(self):
        return CursorKind.from_id(self.cursorKind)

    @property
    def string(self):
        return CompletionString(self.completionString)

class CCRStructure(Structure):
    _fields_ = [('results', POINTER(CodeCompletionResult)),
                ('numResults', c_int)]

    def __len__(self):
        return self.numResults

    def __getitem__(self, key):
        if len(self) <= key:
            raise IndexError

        return self.results[key]

class CodeCompletionResults(ClangObject):
    def __init__(self, ptr):
        assert isinstance(ptr, POINTER(CCRStructure)) and ptr
        self.ptr = self._as_parameter_ = ptr

    def from_param(self):
        return self._as_parameter_

    def __del__(self):
        CodeCompletionResults_dispose(self)

    def sort(self):
        CodeCompletionResults_sort(self.results.results, len(self.results))

    @property
    def results(self):
        return self.ptr.contents

    @property
    def diagnostics(self):
        class DiagnosticsItr:
            def __init__(self, ccr):
                self.ccr= ccr

            def __len__(self):
                return int(_clang_codeCompleteGetNumDiagnostics(self.ccr))

            def __getitem__(self, key):
                diag = _clang_codeCompleteGetDiagnostic(self.ccr, key)
                if not diag:
                    raise IndexError
                return Diagnostic(diag)

        return DiagnosticsItr(self)

def makeString(value):
    if not isinstance(value, str):
        value = value.encode("ascii", "ignore")
    if not isinstance(value, str):
        raise TypeError,'Unexpected unsaved file contents.'
    return value

class Index(ClangObject):
    """
    The Index type provides the primary interface to the Clang CIndex library,
    primarily by providing an interface for reading and parsing translation
    units.
    """

    @staticmethod
    def create(excludeDecls=False):
        """
        Create a new Index.
        Parameters:
        excludeDecls -- Exclude local declarations from translation units.
        """
        return Index(Index_create(excludeDecls, 0))

    def __del__(self):
        Index_dispose(self)

    def read(self, path):
        """Load the translation unit from the given AST file."""
        ptr = TranslationUnit_read(self, path)
        return TranslationUnit(ptr) if ptr else None

    def parse(self, path, args = [], unsaved_files = [], options = 0):
        """
        Load the translation unit from the given source code file by running
        clang and generating the AST before loading. Additional command line
        parameters can be passed to clang via the args parameter.

        In-memory contents for files can be provided by passing a list of pairs
        to as unsaved_files, the first item should be the filenames to be mapped
        and the second should be the contents to be substituted for the
        file. The contents may be passed as strings or file objects.
        """
        arg_array = 0
        if len(args):
            arg_array = (c_char_p * len(args))(* args)
        unsaved_files_array = 0
        if len(unsaved_files):
            unsaved_files_array = (_CXUnsavedFile * len(unsaved_files))()
            for i,(name,value) in enumerate(unsaved_files):
                value = makeString(value)
                unsaved_files_array[i].name = name
                unsaved_files_array[i].contents = value
                unsaved_files_array[i].length = len(value)
        ptr = TranslationUnit_parse(self, path, arg_array, len(args),
                                    unsaved_files_array, len(unsaved_files),
                                    options)
        return TranslationUnit(ptr) if ptr else None


class TranslationUnit(ClangObject):
    """
    The TranslationUnit class represents a source code translation unit and
    provides read-only access to its top-level declarations.
    """

    def __init__(self, ptr, doDispose=True):
        ClangObject.__init__(self, ptr)
        self.doDispose = doDispose

    def __del__(self):
        if self.doDispose:
            TranslationUnit_dispose(self)

    @property
    def cursor(self):
        """Retrieve the cursor that represents the given translation unit."""
        return TranslationUnit_cursor(self)

    @property
    def spelling(self):
        """Get the original translation unit source file name."""
        return TranslationUnit_spelling(self)

    def get_includes(self):
        """
        Return an iterable sequence of FileInclusion objects that describe the
        sequence of inclusions in a translation unit. The first object in
        this sequence is always the input file. Note that this method will not
        recursively iterate over header files included through precompiled
        headers.
        """
        def visitor(fobj, lptr, depth, includes):
            if depth > 0:
                loc = lptr.contents
                includes.append(FileInclusion(loc.file, File(fobj), loc, depth))

        # Automatically adapt CIndex/ctype pointers to python objects
        includes = []
        TranslationUnit_includes(self,
                                 TranslationUnit_includes_callback(visitor),
                                 includes)
        return iter(includes)

    @property
    def diagnostics(self):
        """
        Return an iterable (and indexable) object containing the diagnostics.
        """
        class DiagIterator:
            def __init__(self, tu):
                self.tu = tu

            def __len__(self):
                return int(_clang_getNumDiagnostics(self.tu))

            def __getitem__(self, key):
                diag = _clang_getDiagnostic(self.tu, key)
                if not diag:
                    raise IndexError
                return Diagnostic(diag)

        return DiagIterator(self)

    def reparse(self, unsaved_files = [], options = 0):
        """
        Reparse an already parsed translation unit.

        In-memory contents for files can be provided by passing a list of pairs
        as unsaved_files, the first items should be the filenames to be mapped
        and the second should be the contents to be substituted for the
        file. The contents may be passed as strings or file objects.
        """
        unsaved_files_array = 0
        if len(unsaved_files):
            unsaved_files_array = (_CXUnsavedFile * len(unsaved_files))()
            for i,(name,value) in enumerate(unsaved_files):
                value = makeString(value)
                unsaved_files_array[i].name = name
                unsaved_files_array[i].contents = value
                unsaved_files_array[i].length = len(value)
        ptr = TranslationUnit_reparse(self, len(unsaved_files),
                                      unsaved_files_array,
                                      options)
    def codeComplete(self, path, line, column, unsaved_files = [], options = 0):
        """
        Code complete in this translation unit.

        In-memory contents for files can be provided by passing a list of pairs
        as unsaved_files, the first items should be the filenames to be mapped
        and the second should be the contents to be substituted for the
        file. The contents may be passed as strings or file objects.
        """
        unsaved_files_array = 0
        if len(unsaved_files):
            unsaved_files_array = (_CXUnsavedFile * len(unsaved_files))()
            for i,(name,value) in enumerate(unsaved_files):
                value = makeString(value)
                unsaved_files_array[i].name = name
                unsaved_files_array[i].contents = value
                unsaved_files_array[i].length = len(value)
        ptr = TranslationUnit_codeComplete(self, path,
                                           line, column,
                                           unsaved_files_array,
                                           len(unsaved_files),
                                           options)
        return CodeCompletionResults(ptr) if ptr else None


class File(ClangObject):
    """
    The File class represents a particular source file that is part of a
    translation unit.
    """

    @property
    def name(self):
        """Return the complete file and path name of the file."""
        return _CXString_getCString(File_name(self))

    @property
    def time(self):
        """Return the last modification time of the file."""
        return File_time(self)

class FileInclusion(object):
    """
    The FileInclusion class represents the inclusion of one source file by
    another via a '#include' directive or as the input file for the translation
    unit. This class provides information about the included file, the including
    file, the location of the '#include' directive and the depth of the included
    file in the stack. Note that the input file has depth 0.
    """

    def __init__(self, src, tgt, loc, depth):
        self.source = src
        self.include = tgt
        self.location = loc
        self.depth = depth

    @property
    def is_input_file(self):
        """True if the included file is the input file."""
        return self.depth == 0

# Additional Functions and Types

# String Functions
_CXString_dispose = lib.clang_disposeString
_CXString_dispose.argtypes = [_CXString]
if isWin64:
    _CXString_dispose.argtypes = [POINTER(_CXString)]

_CXString_getCString = lib.clang_getCString
_CXString_getCString.argtypes = [_CXString]
_CXString_getCString.restype = c_char_p
if isWin64:
    _CXString_getCString.argtypes = [POINTER(_CXString)]

# Source Location Functions
SourceLocation_loc = lib.clang_getInstantiationLocation
SourceLocation_loc.argtypes = [SourceLocation, POINTER(c_object_p),
                               POINTER(c_uint), POINTER(c_uint),
                               POINTER(c_uint)]
if isWin64:
    SourceLocation_loc.argtypes = [POINTER(SourceLocation), POINTER(c_object_p),
                                   POINTER(c_uint), POINTER(c_uint),
                                   POINTER(c_uint)]

_clang_getLocation = lib.clang_getLocation
_clang_getLocation.argtypes = [TranslationUnit, File, c_uint, c_uint]
_clang_getLocation.restype = SourceLocation


# Source Range Functions
SourceRange_getRange = lib.clang_getRange
SourceRange_getRange.argtypes = [SourceLocation, SourceLocation]
SourceRange_getRange.restype = SourceRange
if isWin64:
    SourceRange_getRange.argtypes = [POINTER(SourceLocation), POINTER(SourceLocation)]

SourceRange_start = lib.clang_getRangeStart
SourceRange_start.argtypes = [SourceRange]
SourceRange_start.restype = SourceLocation
if isWin64:
    SourceRange_start.argtypes = [POINTER(SourceRange)]

SourceRange_end = lib.clang_getRangeEnd
SourceRange_end.argtypes = [SourceRange]
SourceRange_end.restype = SourceLocation
if isWin64:
    SourceRange_end.argtypes = [POINTER(SourceRange)]

# CursorKind Functions
CursorKind_is_decl = lib.clang_isDeclaration
CursorKind_is_decl.argtypes = [CursorKind]
CursorKind_is_decl.restype = bool

CursorKind_is_ref = lib.clang_isReference
CursorKind_is_ref.argtypes = [CursorKind]
CursorKind_is_ref.restype = bool

CursorKind_is_expr = lib.clang_isExpression
CursorKind_is_expr.argtypes = [CursorKind]
CursorKind_is_expr.restype = bool

CursorKind_is_stmt = lib.clang_isStatement
CursorKind_is_stmt.argtypes = [CursorKind]
CursorKind_is_stmt.restype = bool
"""
CursorKind_is_attribute = lib.clang_isAttribute
CursorKind_is_attribute.argtypes = [CursorKind]
CursorKind_is_attribute.restype = bool
"""

CursorKind_is_inv = lib.clang_isInvalid
CursorKind_is_inv.argtypes = [CursorKind]
CursorKind_is_inv.restype = bool

# Cursor Functions
# TODO: Implement this function
Cursor_get = lib.clang_getCursor
Cursor_get.argtypes = [TranslationUnit, SourceLocation]
Cursor_get.restype = Cursor
if isWin64:
    Cursor_get.argtypes = [TranslationUnit, POINTER(SourceLocation)]

Cursor_null = lib.clang_getNullCursor
Cursor_null.restype = Cursor

Cursor_usr = lib.clang_getCursorUSR
Cursor_usr.argtypes = [Cursor]
Cursor_usr.restype = _CXString
Cursor_usr.errcheck = _CXString.from_result
if isWin64:
    Cursor_usr.argtypes = [POINTER(Cursor)]

Cursor_is_def = lib.clang_isCursorDefinition
Cursor_is_def.argtypes = [Cursor]
Cursor_is_def.restype = bool
if isWin64:
    Cursor_is_def.argtypes = [POINTER(Cursor)]

Cursor_def = lib.clang_getCursorDefinition
Cursor_def.argtypes = [Cursor]
Cursor_def.restype = Cursor
Cursor_def.errcheck = Cursor.from_result
if isWin64:
    Cursor_def.argtypes = [POINTER(Cursor)]

Cursor_eq = lib.clang_equalCursors
Cursor_eq.argtypes = [Cursor, Cursor]
Cursor_eq.restype = c_uint
if isWin64:
    Cursor_eq.argtypes = [POINTER(Cursor), POINTER(Cursor)]

Cursor_spelling = lib.clang_getCursorSpelling
Cursor_spelling.argtypes = [Cursor]
Cursor_spelling.restype = _CXString
Cursor_spelling.errcheck = _CXString.from_result
if isWin64:
    Cursor_spelling.argtypes = [POINTER(Cursor)]

_clang_getCursorCompletionString = lib.clang_getCursorCompletionString
_clang_getCursorCompletionString.argtypes = [Cursor]
_clang_getCursorCompletionString.restype = c_object_p
if isWin64:
    _clang_getCursorCompletionString.argtypes = [POINTER(Cursor)]

Cursor_displayname = lib.clang_getCursorDisplayName
Cursor_displayname.argtypes = [Cursor]
Cursor_displayname.restype = _CXString
Cursor_displayname.errcheck = _CXString.from_result
if isWin64:
    Cursor_displayname.argtypes = [POINTER(Cursor)]

Cursor_loc = lib.clang_getCursorLocation
Cursor_loc.argtypes = [Cursor]
Cursor_loc.restype = SourceLocation
if isWin64:
    Cursor_loc.argtypes = [POINTER(Cursor)]

Cursor_extent = lib.clang_getCursorExtent
Cursor_extent.argtypes = [Cursor]
Cursor_extent.restype = SourceRange
if isWin64:
    Cursor_extent.argtypes = [POINTER(Cursor)]

Cursor_getTranslationUnit = lib.clang_Cursor_getTranslationUnit
Cursor_getTranslationUnit.argtypes = [Cursor]
Cursor_getTranslationUnit.restype = c_object_p
if isWin64:
    Cursor_getTranslationUnit.argtypes = [POINTER(Cursor)]

Cursor_ref = lib.clang_getCursorReferenced
Cursor_ref.argtypes = [Cursor]
Cursor_ref.restype = Cursor
Cursor_ref.errcheck = Cursor.from_result
if isWin64:
    Cursor_ref.argtypes = [POINTER(Cursor)]

Cursor_semanticParent = lib.clang_getCursorSemanticParent
Cursor_semanticParent.argtypes = [Cursor]
Cursor_semanticParent.restype = Cursor
if isWin64:
    Cursor_semanticParent.argtypes = [POINTER(Cursor)]

Cursor_lexicalParent = lib.clang_getCursorLexicalParent
Cursor_lexicalParent.argtypes = [Cursor]
Cursor_lexicalParent.restype = Cursor
if isWin64:
    Cursor_lexicalParent.argtypes = [POINTER(Cursor)]

Cursor_get_canonical = lib.clang_getCanonicalCursor
Cursor_get_canonical.argtypes = [Cursor]
Cursor_get_canonical.restype = Cursor
Cursor_get_canonical.errcheck = Cursor.from_result
if isWin64:
    Cursor_get_canonical.argtypes = [POINTER(Cursor)]

_clang_getSpecializedCursorTemplate = lib.clang_getSpecializedCursorTemplate
_clang_getSpecializedCursorTemplate.argtypes = [Cursor]
_clang_getSpecializedCursorTemplate.restype = Cursor
_clang_getSpecializedCursorTemplate.errcheck = Cursor.from_result
if isWin64:
    _clang_getSpecializedCursorTemplate.argtypes = [POINTER(Cursor)]

_clang_getCursorReferenceNameRange = lib.clang_getCursorReferenceNameRange
_clang_getCursorReferenceNameRange.argtypes = [Cursor, c_int, c_int]
_clang_getCursorReferenceNameRange.restype = SourceRange
if isWin64:
    _clang_getCursorReferenceNameRange.argtypes = [POINTER(Cursor), c_int, c_int]

Cursor_get_linkage = lib.clang_getCursorLinkage
Cursor_get_linkage.argtypes = [Cursor]
Cursor_get_linkage.restype = c_uint
if isWin64:
    Cursor_get_linkage.argtypes = [POINTER(Cursor)]

Cursor_type = lib.clang_getCursorType
Cursor_type.argtypes = [Cursor]
Cursor_type.restype = Type
Cursor_type.errcheck = Type.from_result
if isWin64:
    Cursor_type.argtypes = [POINTER(Cursor)]

_clang_getCursorAvailability = lib.clang_getCursorAvailability
_clang_getCursorAvailability.argtypes = [Cursor]
_clang_getCursorAvailability.restype = c_int
if isWin64:
    _clang_getCursorAvailability.argtypes = [POINTER(Cursor)]

_clang_getCXXAccessSpecifier = lib.clang_getCXXAccessSpecifier
_clang_getCXXAccessSpecifier.argtypes = [Cursor]
_clang_getCXXAccessSpecifier.restype = c_int
if isWin64:
    _clang_getCXXAccessSpecifier.argtypes = [POINTER(Cursor)]

_clang_CXXMethod_isStatic = lib.clang_CXXMethod_isStatic
_clang_CXXMethod_isStatic.argtypes = [Cursor]
_clang_CXXMethod_isStatic.restype = c_int
if isWin64:
    _clang_CXXMethod_isStatic.argtypes = [POINTER(Cursor)]

_clang_getCursorResultType = lib.clang_getCursorResultType
_clang_getCursorResultType.argtypes = [Cursor]
_clang_getCursorResultType.restype = Type
_clang_getCursorResultType.errcheck = Type.from_result
if isWin64:
    _clang_getCursorResultType.argtypes = [POINTER(Cursor)]


Cursor_visit_callback = CFUNCTYPE(c_int, Cursor, Cursor, py_object)
Cursor_visit = lib.clang_visitChildren
Cursor_visit.argtypes = [Cursor, Cursor_visit_callback, py_object]
Cursor_visit.restype = c_uint
if isWin64:
    Cursor_visit_callback = CFUNCTYPE(c_int, POINTER(Cursor), POINTER(Cursor), py_object)
    Cursor_visit.argtypes = [POINTER(Cursor), Cursor_visit_callback, py_object]

Cursor_getOverridden = lib.clang_getOverriddenCursors
Cursor_getOverridden.argtypes = [Cursor, POINTER(POINTER(Cursor)), POINTER(c_int)]
if isWin64:
    Cursor_getOverridden.argtypes = [POINTER(Cursor), POINTER(POINTER(Cursor)), POINTER(c_int)]

Cursor_disposeOverridden = lib.clang_disposeOverriddenCursors
Cursor_disposeOverridden.argtypes = [POINTER(Cursor)]

# Type Functions
Type_get_canonical = lib.clang_getCanonicalType
Type_get_canonical.argtypes = [Type]
Type_get_canonical.restype = Type
Type_get_canonical.errcheck = Type.from_result
if isWin64:
    Type_get_canonical.argtypes = [POINTER(Type)]

Type_is_const_qualified = lib.clang_isConstQualifiedType
Type_is_const_qualified.argtypes = [Type]
Type_is_const_qualified.restype = bool
if isWin64:
    Type_is_const_qualified.argtypes = [POINTER(Type)]

Type_is_volatile_qualified = lib.clang_isVolatileQualifiedType
Type_is_volatile_qualified.argtypes = [Type]
Type_is_volatile_qualified.restype = bool
if isWin64:
    Type_is_volatile_qualified.argtypes = [POINTER(Type)]

Type_is_restrict_qualified = lib.clang_isRestrictQualifiedType
Type_is_restrict_qualified.argtypes = [Type]
Type_is_restrict_qualified.restype = bool
if isWin64:
    Type_is_restrict_qualified.argtypes = [POINTER(Type)]

Type_get_pointee = lib.clang_getPointeeType
Type_get_pointee.argtypes = [Type]
Type_get_pointee.restype = Type
Type_get_pointee.errcheck = Type.from_result
if isWin64:
    Type_get_pointee.argtypes = [POINTER(Type)]

Type_get_declaration = lib.clang_getTypeDeclaration
Type_get_declaration.argtypes = [Type]
Type_get_declaration.restype = Cursor
Type_get_declaration.errcheck = Cursor.from_result
if isWin64:
    Type_get_declaration.argtypes = [POINTER(Type)]

Type_get_result = lib.clang_getResultType
Type_get_result.argtypes = [Type]
Type_get_result.restype = Type
Type_get_result.errcheck = Type.from_result
if isWin64:
    Type_get_result.argtypes = [POINTER(Type)]

_clang_getArrayElementType = lib.clang_getArrayElementType
_clang_getArrayElementType.argtypes = [Type]
_clang_getArrayElementType.restype = Type
_clang_getArrayElementType.errcheck = Type.from_result
if isWin64:
    _clang_getArrayElementType.argtypes = [POINTER(Type)]

# Index Functions
Index_create = lib.clang_createIndex
Index_create.argtypes = [c_int, c_int]
Index_create.restype = c_object_p

Index_dispose = lib.clang_disposeIndex
Index_dispose.argtypes = [Index]

# Translation Unit Functions
TranslationUnit_read = lib.clang_createTranslationUnit
TranslationUnit_read.argtypes = [Index, c_char_p]
TranslationUnit_read.restype = c_object_p

TranslationUnit_parse = lib.clang_parseTranslationUnit
TranslationUnit_parse.argtypes = [Index, c_char_p, c_void_p,
                                  c_int, c_void_p, c_int, c_int]
TranslationUnit_parse.restype = c_object_p

TranslationUnit_reparse = lib.clang_reparseTranslationUnit
TranslationUnit_reparse.argtypes = [TranslationUnit, c_int, c_void_p, c_int]
TranslationUnit_reparse.restype = c_int

TranslationUnit_codeComplete = lib.clang_codeCompleteAt
TranslationUnit_codeComplete.argtypes = [TranslationUnit, c_char_p, c_int,
                                         c_int, c_void_p, c_int, c_int]
TranslationUnit_codeComplete.restype = POINTER(CCRStructure)

TranslationUnit_cursor = lib.clang_getTranslationUnitCursor
TranslationUnit_cursor.argtypes = [TranslationUnit]
TranslationUnit_cursor.restype = Cursor
TranslationUnit_cursor.errcheck = Cursor.from_result

TranslationUnit_spelling = lib.clang_getTranslationUnitSpelling
TranslationUnit_spelling.argtypes = [TranslationUnit]
TranslationUnit_spelling.restype = _CXString
TranslationUnit_spelling.errcheck = _CXString.from_result

TranslationUnit_dispose = lib.clang_disposeTranslationUnit
TranslationUnit_dispose.argtypes = [TranslationUnit]

TranslationUnit_includes_callback = CFUNCTYPE(None,
                                              c_object_p,
                                              POINTER(SourceLocation),
                                              c_uint, py_object)
TranslationUnit_includes = lib.clang_getInclusions
TranslationUnit_includes.argtypes = [TranslationUnit,
                                     TranslationUnit_includes_callback,
                                     py_object]

# File Functions
File_name = lib.clang_getFileName
File_name.argtypes = [File]
File_name.restype = _CXString

File_time = lib.clang_getFileTime
File_time.argtypes = [File]
File_time.restype = c_uint

_clang_getFile = lib.clang_getFile
_clang_getFile.argtypes = [TranslationUnit, c_char_p]
_clang_getFile.restype = c_object_p

_clang_getIncludedFile = lib.clang_getIncludedFile
_clang_getIncludedFile.argtypes = [Cursor]
_clang_getIncludedFile.restype = c_object_p
if isWin64:
    _clang_getIncludedFile.argtypes = [POINTER(Cursor)]

# Code completion

CodeCompletionResults_dispose = lib.clang_disposeCodeCompleteResults
CodeCompletionResults_dispose.argtypes = [CodeCompletionResults]

CodeCompletionResults_sort = lib.clang_sortCodeCompletionResults
CodeCompletionResults_sort.argtypes = [POINTER(CodeCompletionResult), c_int]

_clang_codeCompleteGetNumDiagnostics = lib.clang_codeCompleteGetNumDiagnostics
_clang_codeCompleteGetNumDiagnostics.argtypes = [CodeCompletionResults]
_clang_codeCompleteGetNumDiagnostics.restype = c_int

_clang_codeCompleteGetDiagnostic = lib.clang_codeCompleteGetDiagnostic
_clang_codeCompleteGetDiagnostic.argtypes = [CodeCompletionResults, c_int]
_clang_codeCompleteGetDiagnostic.restype = c_object_p

_clang_getCompletionChunkText = lib.clang_getCompletionChunkText
_clang_getCompletionChunkText.argtypes = [c_void_p, c_int]
_clang_getCompletionChunkText.restype = _CXString

_clang_getCompletionChunkKind = lib.clang_getCompletionChunkKind
_clang_getCompletionChunkKind.argtypes = [c_void_p, c_int]
_clang_getCompletionChunkKind.restype = c_int

_clang_getCompletionChunkCompletionString = lib.clang_getCompletionChunkCompletionString
_clang_getCompletionChunkCompletionString.argtypes = [c_void_p, c_int]
_clang_getCompletionChunkCompletionString.restype = c_object_p


_clang_getNumCompletionChunks = lib.clang_getNumCompletionChunks
_clang_getNumCompletionChunks.argtypes = [c_void_p]
_clang_getNumCompletionChunks.restype = c_int

_clang_getCompletionAvailability = lib.clang_getCompletionAvailability
_clang_getCompletionAvailability.argtypes = [c_void_p]
_clang_getCompletionAvailability.restype = c_int

_clang_getCompletionPriority = lib.clang_getCompletionPriority
_clang_getCompletionPriority.argtypes = [c_void_p]
_clang_getCompletionPriority.restype = c_int


### Tokens ###

class TokenKind(object):
    """
    Describes the kind of token.
    """

    # The unique kind objects, indexed by id.
    _kinds = []
    _name_map = None

    def __init__(self, value):
        if value >= len(TokenKind._kinds):
            TokenKind._kinds += [None] * (value - len(TokenKind._kinds) + 1)
        self.value = value
        TokenKind._kinds[value] = self
        TokenKind._name_map = None

    def from_param(self):
        return self.value

    @property
    def name(self):
        """Get the enumeration name of this token kind."""
        if self._name_map is None:
            self._name_map = {}
            for key, value in TokenKind.__dict__.items():
                if isinstance(value, TokenKind):
                    self._name_map[value] = key
        return self._name_map[self]

    def __eq__(self, other):
        return self.value == other.value

    def __ne__(self, other):
        return self.value != other.value

    def __hash__(self):
        return self.value

    def __repr__(self):
        return 'TokenKind.%s' % (self.name,)

# A token that contains some kind of punctuation.
TokenKind.PUNCTUATION = TokenKind(0)

# A language keyword.
TokenKind.KEYWORD = TokenKind(1)

# An identifier (that is not a keyword).
TokenKind.IDENTIFIER = TokenKind(2)

# A numeric, string, or character literal.
TokenKind.LITERAL = TokenKind(3)

# A comment.
TokenKind.COMMENT = TokenKind(4)


class TokenImpl(Structure):
    """
    The TokenImpl class reprents an entry in a CXToken array (of type
    CXToken *).
    """
    _fields_ = [("int_data", c_uint * 4), ("ptr_data", c_void_p)]

    def kind(self):
        """Return the TokenKind of the token."""
        if not hasattr(self, '_kind'):
            self._kind = Token_kind(self)
        return self._kind

    def spelling(self, translation_unit):
        """Return the spelling of the token."""
        #import pdb; pdb.set_trace()
        if not hasattr(self, '_spelling'):
            self._spelling = Token_spelling(translation_unit, self)
        return self._spelling

    def location(self, translation_unit):
        """Return the location of the token."""
        if not hasattr(self, '_location'):
            self._location = Token_location(translation_unit, self)
        return self._location

    def extent(self, translation_unit):
        """Return the extent of the token."""
        if not hasattr(self, '_extent'):
            self._extent = Token_extent(translation_unit, self)
        return self._extent


class Token(object):
    """The front-end representation of a token.

    We can only allocate tokens in arrays.  The role of this class is to be used
    externally.  Objects of this type hold a reference to the TokenImpl class
    through which the internal libclang methods are called.

    It also holds a reference to its owning TokenCollection so the
    TokenCollection object can only be freed after all referneces to all of its
    Tokens have been released.
    """

    def __init__(self, translation_unit, token_impl, collection):
        self.translation_unit = translation_unit
        self.token_impl = token_impl
        self.collection = collection

    @property
    def kind(self):
        return self.token_impl.kind()

    @property
    def spelling(self):
        return self.token_impl.spelling(self.translation_unit)

    @property
    def location(self):
        return self.token_impl.location(self.translation_unit)

    @property
    def extent(self):
        return self.token_impl.extent(self.translation_unit)


class TokenCollection(object):
    """Holds a C array of TokenImpl objects.

    These are presented to the outside by Token objects.
    """

    def __init__(self, translation_unit, source_range, token_arr, num_tokens):
        self.translation_unit = translation_unit
        self.source_range = source_range
        self._token_arr = token_arr
        self._num_tokens = num_tokens
        self.tokens = tuple(Token(self.translation_unit, self._token_arr[i], self) for i in range(self._num_tokens.value))
        self.cursors = None

    def annotate(self):
        self._cursors = (Cursor * self._num_tokens.value)()
        _clang_annotateTokens(self.translation_unit, self._token_arr, self._num_tokens, self._cursors)

    def get_cursor(self, idx):
        return self._cursors[idx]

    def __iter__(self):
        return iter(self.tokens)

    def __getitem__(self, i):
        return self.tokens[i]

    def __len__(self):
        return len(self.tokens)

    def __del__(self):
        _clang_disposeTokens(self.translation_unit, self._token_arr, self._num_tokens)


def tokenize(translation_unit, source_range):
    """Tokenize a source range in the given translation unit."""
    tokens = POINTER(TokenImpl)()
    num_tokens = c_uint()
    _clang_tokenize(translation_unit, source_range, tokens, byref(num_tokens))
    return TokenCollection(translation_unit, source_range, tokens, num_tokens)


Token_kind = lib.clang_getTokenKind
Token_kind.argtypes = [TokenImpl]
Token_kind.restype = TokenKind

Token_spelling = lib.clang_getTokenSpelling
Token_spelling.argtypes = [TranslationUnit, TokenImpl]
Token_spelling.restype = _CXString
Token_spelling.errcheck = _CXString.from_result

Token_location = lib.clang_getTokenLocation
Token_location.argtypes = [TranslationUnit, TokenImpl]
Token_location.restype = SourceLocation

Token_extent = lib.clang_getTokenExtent
Token_extent.argtypes = [TranslationUnit, TokenImpl]
Token_extent.restype = SourceRange

_clang_tokenize = lib.clang_tokenize
_clang_tokenize.argtypes = [TranslationUnit, SourceRange, POINTER(POINTER(TokenImpl)), POINTER(c_uint)]

_clang_annotateTokens = lib.clang_annotateTokens
_clang_annotateTokens.argtypes = [TranslationUnit, POINTER(TokenImpl), c_uint, POINTER(Cursor)]

_clang_disposeTokens = lib.clang_disposeTokens
_clang_disposeTokens.argtypes = [TranslationUnit, POINTER(TokenImpl), c_uint]


###

__all__ = ['Index', 'TranslationUnit', 'Cursor', 'CursorKind', 'Type', 'TypeKind',
           'Diagnostic', 'FixIt', 'CodeCompletionResults', 'SourceRange',
           'SourceLocation', 'File', 'Token', 'TokenKind']