# Copyright 2021 The Cirq Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import abc
import dataclasses
from typing import Any, Mapping, TYPE_CHECKING

import attrs
import sympy

from cirq._compat import proper_repr
from cirq.protocols import json_serialization, measurement_key_protocol as mkp
from cirq.value import measurement_key

if TYPE_CHECKING:
    import cirq


class Condition(abc.ABC):
    """A classical control condition that can gate an operation."""

    @property
    @abc.abstractmethod
    def keys(self) -> tuple[cirq.MeasurementKey, ...]:
        """Gets the control keys."""

    @abc.abstractmethod
    def replace_key(self, current: cirq.MeasurementKey, replacement: cirq.MeasurementKey):
        """Replaces the control keys."""

    @abc.abstractmethod
    def resolve(self, classical_data: cirq.ClassicalDataStoreReader) -> bool:
        """Resolves the condition based on the measurements."""

    @property
    @abc.abstractmethod
    def qasm(self):
        """Returns the qasm of this condition."""

    def _qasm_(self, args: cirq.QasmArgs, **kwargs) -> str | None:
        return self.qasm

    def _with_measurement_key_mapping_(self, key_map: Mapping[str, str]) -> cirq.Condition:
        condition = self
        for k in self.keys:
            condition = condition.replace_key(k, mkp.with_measurement_key_mapping(k, key_map))
        return condition

    def _with_key_path_prefix_(self, path: tuple[str, ...]) -> cirq.Condition:
        condition = self
        for k in self.keys:
            condition = condition.replace_key(k, mkp.with_key_path_prefix(k, path))
        return condition

    def _with_rescoped_keys_(
        self, path: tuple[str, ...], bindable_keys: frozenset[cirq.MeasurementKey]
    ) -> cirq.Condition:
        condition = self
        for key in self.keys:
            for i in range(len(path) + 1):
                back_path = path[: len(path) - i]
                new_key = key.with_key_path_prefix(*back_path)
                if new_key in bindable_keys:
                    condition = condition.replace_key(key, new_key)
                    break
        return condition


@dataclasses.dataclass(frozen=True)
class KeyCondition(Condition):
    """A classical control condition based on a single measurement key.

    This condition resolves to True iff the measurement key is non-zero at the
    time of resolution.
    """

    key: cirq.MeasurementKey
    index: int = -1

    @property
    def keys(self):
        return (self.key,)

    def replace_key(self, current: cirq.MeasurementKey, replacement: cirq.MeasurementKey):
        return KeyCondition(replacement) if self.key == current else self

    def __str__(self):
        return str(self.key) if self.index == -1 else f'{self.key}[{self.index}]'

    def __repr__(self):
        if self.index != -1:
            return f'cirq.KeyCondition({self.key!r}, {self.index})'
        return f'cirq.KeyCondition({self.key!r})'

    def resolve(self, classical_data: cirq.ClassicalDataStoreReader) -> bool:
        if self.key not in classical_data.keys():
            raise ValueError(f'Measurement key {self.key} missing when testing classical control')
        return classical_data.get_int(self.key, self.index) != 0

    def _json_dict_(self):
        return json_serialization.dataclass_json_dict(self)

    @classmethod
    def _from_json_dict_(cls, key, **kwargs):
        return cls(key=key)

    @property
    def qasm(self):
        raise ValueError('QASM is defined only for SympyConditions of type key == constant.')

    def _qasm_(self, args: cirq.QasmArgs, **kwargs) -> str | None:
        args.validate_version('2.0', '3.0')
        key_str = str(self.key)
        if key_str not in args.meas_key_id_map:
            raise ValueError(f'Key "{key_str}" not in QasmArgs.meas_key_id_map.')
        key = args.meas_key_id_map[key_str]
        # QASM 3.0 supports !=, so we return it directly.
        if args.version == '3.0':
            return f'{key}!=0'
        # QASM 2.0 only has == operator, so we must limit to single-bit measurement keys == 1.
        if key not in args.meas_key_bitcount:
            raise ValueError(f'Key "{key}" not in QasmArgs.meas_key_bitcount.')
        if args.meas_key_bitcount[str(key)] != 1:
            raise ValueError('QASM is defined only for single-bit classical conditions.')
        return f'{key}==1'


@attrs.frozen
class BitMaskKeyCondition(Condition):
    """A multiqubit classical control condition with a bitmask.

    The control is based on a single measurement key and allows comparing equality or inequality
    after taking the bitwise and with a bitmask.

    Examples:
        - BitMaskKeyCondition('a') -> a != 0
        - BitMaskKeyCondition('a', bitmask=13) -> (a & 13) != 0
        - BitMaskKeyCondition('a', bitmask=13, target_value=9) -> (a & 13) != 9
        - BitMaskKeyCondition('a', bitmask=13, target_value=9, equal_target=True) -> (a & 13) == 9
        - BitMaskKeyCondition.create_equal_mask('a', 13) -> (a & 13) == 13
        - BitMaskKeyCondition.create_not_equal_mask('a', 13) -> (a & 13) != 13

    The bits in the bitmask have the same order as the qubits passed to `cirq.measure(...)`. That's
    the most significant bit corresponds to the first (left most) qubit.

    Attributes:
        - key: Measurement key.
        - index: integer index (same as KeyCondition.index).
        - target_value: The value we compare with.
        - equal_target: Whether to comapre with == or !=.
        - bitmask: Optional bitmask to apply before doing the comparison.
    """

    key: cirq.MeasurementKey = attrs.field(
        converter=lambda x: (
            x
            if isinstance(x, measurement_key.MeasurementKey)
            else measurement_key.MeasurementKey(x)
        )
    )
    index: int = -1
    target_value: int = 0
    equal_target: bool = False
    bitmask: int | None = None

    @property
    def keys(self):
        return (self.key,)

    @staticmethod
    def create_equal_mask(
        key: cirq.MeasurementKey, bitmask: int, *, index: int = -1
    ) -> BitMaskKeyCondition:
        """Creates a condition that evaluates (meas & bitmask) == bitmask."""
        return BitMaskKeyCondition(
            key, index, target_value=bitmask, equal_target=True, bitmask=bitmask
        )

    @staticmethod
    def create_not_equal_mask(
        key: cirq.MeasurementKey, bitmask: int, *, index: int = -1
    ) -> BitMaskKeyCondition:
        """Creates a condition that evaluates (meas & bitmask) != bitmask."""
        return BitMaskKeyCondition(
            key, index, target_value=bitmask, equal_target=False, bitmask=bitmask
        )

    def replace_key(self, current: cirq.MeasurementKey, replacement: cirq.MeasurementKey):
        return BitMaskKeyCondition(replacement) if self.key == current else self

    def __str__(self):
        s = str(self.key) if self.index == -1 else f'{self.key}[{self.index}]'
        if self.bitmask is not None:
            s = f'{s} & {self.bitmask}'
        if self.equal_target:
            if self.bitmask is not None:
                s = f'({s})'
            s = f'{s} == {self.target_value}'
        elif self.target_value != 0:
            if self.bitmask is not None:
                s = f'({s})'
            s = f'{s} != {self.target_value}'
        return s

    def __repr__(self):
        values = attrs.asdict(self)
        parameters = ', '.join(f'{f.name}={repr(values[f.name])}' for f in attrs.fields(type(self)))
        return f'cirq.BitMaskKeyCondition({parameters})'

    def resolve(self, classical_data: cirq.ClassicalDataStoreReader) -> bool:
        if self.key not in classical_data.keys():
            raise ValueError(f'Measurement key {self.key} missing when testing classical control')
        value = classical_data.get_int(self.key, self.index)
        if self.bitmask is not None:
            value &= self.bitmask
        if self.equal_target:
            return value == self.target_value
        return value != self.target_value

    def _json_dict_(self):
        return json_serialization.attrs_json_dict(self)

    @classmethod
    def _from_json_dict_(cls, key, **kwargs):
        parameter_names = [f.name for f in attrs.fields(cls)[1:]]
        parameters = {k: kwargs[k] for k in parameter_names if k in kwargs}
        return cls(key=key, **parameters)

    @property
    def qasm(self):
        raise NotImplementedError()


@dataclasses.dataclass(frozen=True)
class SympyCondition(Condition):
    """A classical control condition based on a sympy expression.

    This condition resolves to True iff the sympy expression resolves to a
    truthy value (i.e. `bool(x) == True`) when the measurement keys are
    substituted in as the free variables.

    `sympy.IndexedBase` can be used for bitwise conditions. For example, the
    following will create a condition that is controlled by the XOR of the
    first two bits (big-endian) of measurement 'a'.
    >>> a = sympy.IndexedBase('a')
    >>> cond = cirq.SympyCondition(sympy.Xor(a[0], a[1]))
    """

    expr: sympy.Basic

    @property
    def keys(self):
        return tuple(
            measurement_key.MeasurementKey.parse_serialized(symbol.name)
            for symbol in self.expr.free_symbols
            if isinstance(symbol, sympy.Symbol)
            # For bitwise ops, both Symbol ('a') and Indexed ('a[0]') are returned. We only want to
            # keep the former here.
        )

    def replace_key(self, current: cirq.MeasurementKey, replacement: cirq.MeasurementKey):
        return SympyCondition(self.expr.subs({str(current): sympy.Symbol(str(replacement))}))

    def __str__(self):
        return str(self.expr)

    def __repr__(self):
        return f'cirq.SympyCondition({proper_repr(self.expr)})'

    def resolve(self, classical_data: cirq.ClassicalDataStoreReader) -> bool:
        missing = [str(k) for k in self.keys if k not in classical_data.keys()]
        if missing:
            raise ValueError(f'Measurement keys {missing} missing when testing classical control')

        replacements: dict[str, Any] = {}
        for symbol in self.expr.free_symbols:
            if isinstance(symbol, sympy.Symbol):
                name = symbol.name
                key = measurement_key.MeasurementKey.parse_serialized(name)
                replacements[str(key)] = classical_data.get_int(key)
        for symbol in self.expr.free_symbols:
            if isinstance(symbol, sympy.Indexed):
                name = symbol.base.name
                key = measurement_key.MeasurementKey.parse_serialized(name)
                replacements[str(key)] = tuple(classical_data.get_digits(key))
        value = self.expr.subs(replacements)
        return bool(value)

    def _json_dict_(self):
        return json_serialization.dataclass_json_dict(self)

    @classmethod
    def _from_json_dict_(cls, expr, **kwargs):
        return cls(expr=expr)

    @property
    def qasm(self):
        if isinstance(self.expr, sympy.Equality):
            if isinstance(self.expr.lhs, sympy.Symbol) and isinstance(self.expr.rhs, sympy.Integer):
                # Measurements get prepended with "m_", so the condition needs to be too.
                return f'm_{self.expr.lhs}=={self.expr.rhs}'
        raise ValueError('QASM is defined only for SympyConditions of type key == constant.')
