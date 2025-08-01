# Copyright 2019 The Cirq Developers
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

"""Module for use in exporting cirq-google objects in JSON."""

from __future__ import annotations

import functools
import warnings
from typing import TYPE_CHECKING

from cirq.transformers.heuristic_decompositions.two_qubit_gate_tabulation import (
    TwoQubitGateTabulation,
)

if TYPE_CHECKING:
    from cirq.protocols.json_serialization import ObjectFactory


@functools.lru_cache()
def _class_resolver_dictionary() -> dict[str, ObjectFactory]:
    def _old_xmon(*args, **kwargs):
        d_type = kwargs['constant']
        warnings.warn(
            f'Attempted to json load a {d_type} Device.'
            'These devices were removed in Cirq v0.15 and are no '
            'longer supported. Please update device usage to a '
            'supported device or downgrade your Cirq installation.'
        )
        return str(d_type)

    import cirq_google

    return {
        '_NamedConstantXmonDevice': _old_xmon,
        'AnalogDetuneCouplerOnly': cirq_google.AnalogDetuneCouplerOnly,
        'AnalogDetuneQubit': cirq_google.AnalogDetuneQubit,
        'Calibration': cirq_google.Calibration,
        'CalibrationTag': cirq_google.CalibrationTag,
        'CalibrationLayer': cirq_google.CalibrationLayer,
        'CouplerPulse': cirq_google.experimental.CouplerPulse,
        'Coupler': cirq_google.Coupler,
        'GoogleNoiseProperties': cirq_google.GoogleNoiseProperties,
        'PerQubitDepolarizingWithDampedReadoutNoiseModel': (
            cirq_google.experimental.PerQubitDepolarizingWithDampedReadoutNoiseModel
        ),
        'SycamoreGate': cirq_google.SycamoreGate,
        'WaitGateWithUnit': cirq_google.WaitGateWithUnit,
        'WillowGate': cirq_google.WillowGate,
        # cirq_google.GateTabulation has been removed and replaced by cirq.TwoQubitGateTabulation.
        'GateTabulation': TwoQubitGateTabulation,
        'PhysicalZTag': cirq_google.PhysicalZTag,
        'FSimGateFamily': cirq_google.FSimGateFamily,
        'FSimViaModelTag': cirq_google.FSimViaModelTag,
        'SycamoreTargetGateset': cirq_google.SycamoreTargetGateset,
        'cirq.google.BitstringsMeasurement': cirq_google.BitstringsMeasurement,
        'cirq.google.QuantumExecutable': cirq_google.QuantumExecutable,
        'cirq.google.QuantumExecutableGroup': cirq_google.QuantumExecutableGroup,
        'cirq.google.KeyValueExecutableSpec': cirq_google.KeyValueExecutableSpec,
        'cirq.google.SharedRuntimeInfo': cirq_google.SharedRuntimeInfo,
        'cirq.google.RuntimeInfo': cirq_google.RuntimeInfo,
        'cirq.google.ExecutableResult': cirq_google.ExecutableResult,
        'cirq.google.ExecutableGroupResult': cirq_google.ExecutableGroupResult,
        # Pylint fights with the black formatter.
        'cirq.google.ExecutableGroupResultFilesystemRecord': cirq_google.ExecutableGroupResultFilesystemRecord,  # noqa: E501
        'cirq.google.QuantumRuntimeConfiguration': cirq_google.QuantumRuntimeConfiguration,
        'cirq.google.NaiveQubitPlacer': cirq_google.NaiveQubitPlacer,
        'cirq.google.RandomDevicePlacer': cirq_google.RandomDevicePlacer,
        'cirq.google.EngineProcessorRecord': cirq_google.EngineProcessorRecord,
        'cirq.google.SimulatedProcessorRecord': cirq_google.SimulatedProcessorRecord,
        'cirq.google.SimulatedProcessorWithLocalDeviceRecord': cirq_google.SimulatedProcessorWithLocalDeviceRecord,  # noqa: E501
        'cirq.google.HardcodedQubitPlacer': cirq_google.HardcodedQubitPlacer,
        'cirq.google.EngineResult': cirq_google.EngineResult,
        'cirq.google.GridDevice': cirq_google.GridDevice,
        'cirq.google.GoogleCZTargetGateset': cirq_google.GoogleCZTargetGateset,
        'cirq.google.DeviceParameter': cirq_google.study.device_parameter.DeviceParameter,
        'cirq.google.Metadata': cirq_google.study.device_parameter.Metadata,
        'InternalGate': cirq_google.InternalGate,
        'InternalTag': cirq_google.InternalTag,
    }
