# Copyright 2025 The Cirq Developers
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

import itertools
import random
from typing import Sequence

import numpy as np
import pytest

import cirq
from cirq.contrib.paulistring import measure_pauli_strings
from cirq.contrib.paulistring.pauli_string_measurement_with_readout_mitigation import (
    _process_pauli_measurement_results,
)
from cirq.experiments.single_qubit_readout_calibration import SingleQubitReadoutCalibrationResult
from cirq.experiments.single_qubit_readout_calibration_test import NoisySingleQubitReadoutSampler


def _create_ghz(number_of_qubits: int, qubits: Sequence[cirq.Qid]) -> cirq.Circuit:
    ghz_circuit = cirq.Circuit(
        cirq.H(qubits[0]),
        *[cirq.CNOT(qubits[i - 1], qubits[i]) for i in range(1, number_of_qubits)],
    )
    return ghz_circuit


def _generate_random_pauli_string(
    qubits: Sequence[cirq.Qid], enable_coeff: bool = False, allow_pauli_i: bool = True
):
    pauli_ops = [cirq.I, cirq.X, cirq.Y, cirq.Z]

    if not allow_pauli_i:
        pauli_ops = [cirq.X, cirq.Y, cirq.Z]

    operators = {q: random.choice(pauli_ops) for q in qubits}
    # Ensure at least one non-identity.
    operators[random.choice(qubits)] = random.choice(pauli_ops[1:])

    if enable_coeff:
        coefficient = (2 * random.random() - 1) * 100
        return coefficient * cirq.PauliString(operators)
    return cirq.PauliString(operators)


def _generate_qwc_paulis(
    input_pauli: cirq.PauliString, num_output: int, exclude_input_pauli: bool = False
) -> list[cirq.PauliString]:
    """Generates PauliStrings that are Qubit-Wise Commuting (QWC)
    with the input_pauli.

    All operations in input_pauli must not be pauli I.
    """
    allowed_paulis_per_qubit = []
    qubits = input_pauli.qubits

    for qubit in qubits:
        pauli_op = input_pauli.get(qubit, cirq.I)

        allowed_pauli_op = []
        if pauli_op == cirq.I:
            allowed_pauli_op = [cirq.I, cirq.X, cirq.Y, cirq.Z]  # pragma: no cover
        elif pauli_op == cirq.X:
            allowed_pauli_op = [cirq.I, cirq.X]
        elif pauli_op == cirq.Y:
            allowed_pauli_op = [cirq.I, cirq.Y]
        elif pauli_op == cirq.Z:
            allowed_pauli_op = [cirq.I, cirq.Z]

        allowed_paulis_per_qubit.append(allowed_pauli_op)

    qwc_paulis: list[cirq.PauliString] = []

    for pauli_combination in itertools.product(*allowed_paulis_per_qubit):
        pauli_dict = {}
        for i, qid in enumerate(qubits):
            pauli_dict[qid] = pauli_combination[i]

        qwc_pauli: cirq.PauliString = cirq.PauliString(pauli_dict)
        if exclude_input_pauli and qwc_pauli == input_pauli:
            continue  # pragma: no cover
        if all(q == cirq.I for q in qwc_pauli):
            continue
        qwc_paulis.append(qwc_pauli)

    return qwc_paulis if num_output > len(qwc_paulis) else random.sample(qwc_paulis, num_output)


def _ideal_expectation_based_on_pauli_string(
    pauli_string: cirq.PauliString, final_state_vector: np.ndarray
) -> float:
    return pauli_string.expectation_from_state_vector(
        final_state_vector, qubit_map={q: i for i, q in enumerate(pauli_string.qubits)}
    )


def test_pauli_string_measurement_errors_no_noise() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the Pauli string"""

    qubits = cirq.LineQubit.range(5)
    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))
    sampler = cirq.Simulator()

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [_generate_random_pauli_string(qubits) for _ in range(3)]

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 1000, 1000
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = sampler.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            # Since there is no noise, the mitigated and unmitigated expectations should be the same
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                pauli_string_measurement_results.unmitigated_expectation,
            )
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )
            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )
            assert pauli_string_measurement_results.calibration_result.zero_state_errors == {
                q: 0 for q in pauli_string_measurement_results.pauli_string.qubits
            }
            assert pauli_string_measurement_results.calibration_result.one_state_errors == {
                q: 0 for q in pauli_string_measurement_results.pauli_string.qubits
            }


def test_pauli_string_measurement_errors_with_coefficient_no_noise() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the Pauli string"""

    qubits = cirq.LineQubit.range(5)
    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))
    sampler = cirq.Simulator()

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [_generate_random_pauli_string(qubits, True) for _ in range(3)]

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 1000, 1000
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = sampler.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            # Since there is no noise, the mitigated and unmitigated expectations should be the same
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                pauli_string_measurement_results.unmitigated_expectation,
            )
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )
            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )
            assert pauli_string_measurement_results.calibration_result.zero_state_errors == {
                q: 0 for q in pauli_string_measurement_results.pauli_string.qubits
            }
            assert pauli_string_measurement_results.calibration_result.one_state_errors == {
                q: 0 for q in pauli_string_measurement_results.pauli_string.qubits
            }


def test_group_pauli_string_measurement_errors_no_noise_with_coefficient() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the group of Pauli strings"""

    qubits = cirq.LineQubit.range(5)
    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))
    sampler = cirq.Simulator()

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[list[cirq.PauliString]]] = {}
    circuits_to_pauli[circuit] = [
        _generate_qwc_paulis(
            _generate_random_pauli_string(qubits, enable_coeff=True, allow_pauli_i=False), 100, True
        )
        for _ in range(3)
    ]
    circuits_to_pauli[circuit].append([cirq.PauliString({q: cirq.X for q in qubits})])

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 100, 100, 100, 100
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = sampler.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            # Since there is no noise, the mitigated and unmitigated expectations should be the same
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                pauli_string_measurement_results.unmitigated_expectation,
            )
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )
            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )
            assert pauli_string_measurement_results.calibration_result.zero_state_errors == {
                q: 0 for q in pauli_string_measurement_results.pauli_string.qubits
            }
            assert pauli_string_measurement_results.calibration_result.one_state_errors == {
                q: 0 for q in pauli_string_measurement_results.pauli_string.qubits
            }


def test_pauli_string_measurement_errors_with_noise() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the Pauli string"""
    qubits = cirq.LineQubit.range(7)
    circuit = cirq.FrozenCircuit(_create_ghz(7, qubits))
    sampler = NoisySingleQubitReadoutSampler(p0=0.1, p1=0.005, seed=1234)
    simulator = cirq.Simulator()

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [_generate_random_pauli_string(qubits) for _ in range(3)]

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 1000, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = simulator.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )

            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )

            for (
                error
            ) in pauli_string_measurement_results.calibration_result.zero_state_errors.values():
                assert 0.08 < error < 0.12
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.one_state_errors.values():
                assert 0.0045 < error < 0.0055


def test_group_pauli_string_measurement_errors_with_noise() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the group Pauli strings"""
    qubits = cirq.LineQubit.range(7)
    circuit = cirq.FrozenCircuit(_create_ghz(7, qubits))
    sampler = NoisySingleQubitReadoutSampler(p0=0.1, p1=0.005, seed=1234)
    simulator = cirq.Simulator()

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[list[cirq.PauliString]]] = {}
    circuits_to_pauli[circuit] = [
        _generate_qwc_paulis(
            _generate_random_pauli_string(qubits, enable_coeff=True, allow_pauli_i=False), 5
        )
    ]

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 800, 1000, 800, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = simulator.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )

            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )

            for (
                error
            ) in pauli_string_measurement_results.calibration_result.zero_state_errors.values():
                assert 0.08 < error < 0.12
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.one_state_errors.values():
                assert 0.0045 < error < 0.0055


def test_many_circuits_input_measurement_with_noise() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the Pauli string for multiple circuits"""
    qubits_1 = cirq.LineQubit.range(3)
    qubits_2 = [
        cirq.GridQubit(0, 1),
        cirq.GridQubit(1, 1),
        cirq.GridQubit(1, 0),
        cirq.GridQubit(1, 2),
        cirq.GridQubit(2, 1),
    ]
    qubits_3 = cirq.LineQubit.range(8)

    circuit_1 = cirq.FrozenCircuit(_create_ghz(3, qubits_1))
    circuit_2 = cirq.FrozenCircuit(_create_ghz(5, qubits_2))
    circuit_3 = cirq.FrozenCircuit(_create_ghz(8, qubits_3))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit_1] = [_generate_random_pauli_string(qubits_1) for _ in range(3)]
    circuits_to_pauli[circuit_2] = [_generate_random_pauli_string(qubits_2) for _ in range(3)]
    circuits_to_pauli[circuit_3] = [_generate_random_pauli_string(qubits_3) for _ in range(3)]

    sampler = NoisySingleQubitReadoutSampler(p0=0.03, p1=0.005, seed=1234)
    simulator = cirq.Simulator()

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 1000, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = simulator.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )
            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.zero_state_errors.values():
                assert 0.025 < error < 0.035
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.one_state_errors.values():
                assert 0.0045 < error < 0.0055


def test_allow_measurement_without_readout_mitigation() -> None:
    """Test that the function allows to measure without error mitigation"""
    qubits = cirq.LineQubit.range(7)
    circuit = cirq.FrozenCircuit(_create_ghz(7, qubits))
    sampler = NoisySingleQubitReadoutSampler(p0=0.1, p1=0.005, seed=1234)

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [
        _generate_random_pauli_string(qubits, True),
        _generate_random_pauli_string(qubits),
        _generate_random_pauli_string(qubits),
    ]

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 0, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            # Since there's no mitigation, the mitigated and unmitigated expectations
            # should be the same
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                pauli_string_measurement_results.unmitigated_expectation,
            )
            assert pauli_string_measurement_results.calibration_result is None


def test_allow_group_pauli_measurement_without_readout_mitigation() -> None:
    """Test that the function allows to measure without error mitigation"""
    qubits = cirq.LineQubit.range(7)
    circuit = cirq.FrozenCircuit(_create_ghz(7, qubits))
    sampler = NoisySingleQubitReadoutSampler(p0=0.1, p1=0.005, seed=1234)

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[list[cirq.PauliString]]] = {}
    circuits_to_pauli[circuit] = [
        _generate_qwc_paulis(_generate_random_pauli_string(qubits, True), 2, True),
        _generate_qwc_paulis(_generate_random_pauli_string(qubits), 4),
        _generate_qwc_paulis(_generate_random_pauli_string(qubits), 6),
    ]

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 100, 100, 0, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            # Since there's no mitigation, the mitigated and unmitigated expectations
            # should be the same
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                pauli_string_measurement_results.unmitigated_expectation,
            )
            assert pauli_string_measurement_results.calibration_result is None


def test_many_circuits_with_coefficient() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the Pauli string for multiple circuits"""
    qubits_1 = cirq.LineQubit.range(3)
    qubits_2 = [
        cirq.GridQubit(0, 1),
        cirq.GridQubit(1, 1),
        cirq.GridQubit(1, 0),
        cirq.GridQubit(1, 2),
        cirq.GridQubit(2, 1),
    ]
    qubits_3 = cirq.LineQubit.range(8)

    circuit_1 = cirq.FrozenCircuit(_create_ghz(3, qubits_1))
    circuit_2 = cirq.FrozenCircuit(_create_ghz(5, qubits_2))
    circuit_3 = cirq.FrozenCircuit(_create_ghz(8, qubits_3))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit_1] = [_generate_random_pauli_string(qubits_1, True) for _ in range(3)]
    circuits_to_pauli[circuit_2] = [_generate_random_pauli_string(qubits_2, True) for _ in range(3)]
    circuits_to_pauli[circuit_3] = [_generate_random_pauli_string(qubits_3, True) for _ in range(3)]

    sampler = NoisySingleQubitReadoutSampler(p0=0.03, p1=0.005, seed=1234)
    simulator = cirq.Simulator()

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 1000, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = simulator.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )
            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.zero_state_errors.values():
                assert 0.025 < error < 0.035
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.one_state_errors.values():
                assert 0.0045 < error < 0.0055


def test_many_group_pauli_in_circuits_with_coefficient() -> None:
    """Test that the mitigated expectation is close to the ideal expectation
    based on the Pauli string for multiple circuits"""
    qubits_1 = cirq.LineQubit.range(3)
    qubits_2 = [
        cirq.GridQubit(0, 1),
        cirq.GridQubit(1, 1),
        cirq.GridQubit(1, 0),
        cirq.GridQubit(1, 2),
        cirq.GridQubit(2, 1),
    ]
    qubits_3 = cirq.LineQubit.range(8)

    circuit_1 = cirq.FrozenCircuit(_create_ghz(3, qubits_1))
    circuit_2 = cirq.FrozenCircuit(_create_ghz(5, qubits_2))
    circuit_3 = cirq.FrozenCircuit(_create_ghz(8, qubits_3))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[list[cirq.PauliString]]] = {}
    circuits_to_pauli[circuit_1] = [
        _generate_qwc_paulis(
            _generate_random_pauli_string(qubits_1, enable_coeff=True, allow_pauli_i=False), 4
        )
    ]
    circuits_to_pauli[circuit_2] = [
        _generate_qwc_paulis(
            _generate_random_pauli_string(qubits_2, enable_coeff=True, allow_pauli_i=False), 5
        )
    ]
    circuits_to_pauli[circuit_3] = [
        _generate_qwc_paulis(
            _generate_random_pauli_string(qubits_3, enable_coeff=True, allow_pauli_i=False), 6
        )
    ]

    sampler = NoisySingleQubitReadoutSampler(p0=0.03, p1=0.005, seed=1234)
    simulator = cirq.Simulator()

    circuits_with_pauli_expectations = measure_pauli_strings(
        circuits_to_pauli, sampler, 1000, 1000, 1000, np.random.default_rng()
    )

    for circuit_with_pauli_expectations in circuits_with_pauli_expectations:
        assert isinstance(circuit_with_pauli_expectations.circuit, cirq.FrozenCircuit)

        expected_val_simulation = simulator.simulate(
            circuit_with_pauli_expectations.circuit.unfreeze()
        )
        final_state_vector = expected_val_simulation.final_state_vector

        for pauli_string_measurement_results in circuit_with_pauli_expectations.results:
            assert np.isclose(
                pauli_string_measurement_results.mitigated_expectation,
                _ideal_expectation_based_on_pauli_string(
                    pauli_string_measurement_results.pauli_string, final_state_vector
                ),
                atol=4 * pauli_string_measurement_results.mitigated_stddev,
            )
            assert isinstance(
                pauli_string_measurement_results.calibration_result,
                SingleQubitReadoutCalibrationResult,
            )
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.zero_state_errors.values():
                assert 0.025 < error < 0.035
            for (
                error
            ) in pauli_string_measurement_results.calibration_result.one_state_errors.values():
                assert 0.0045 < error < 0.0055


def test_coefficient_not_real_number() -> None:
    """Test that the coefficient of input pauli string is not real.
    Should return error in this case"""
    qubits_1 = cirq.LineQubit.range(3)
    random_pauli_string = _generate_random_pauli_string(qubits_1, True) * (3 + 4j)
    circuit_1 = cirq.FrozenCircuit(_create_ghz(3, qubits_1))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit_1] = [
        random_pauli_string,
        _generate_random_pauli_string(qubits_1, True),
        _generate_random_pauli_string(qubits_1, True),
    ]

    with pytest.raises(
        ValueError,
        match="Cannot compute expectation value of a "
        "non-Hermitian PauliString. Coefficient must be real.",
    ):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, np.random.default_rng()
        )


def test_empty_input_circuits_to_pauli_mapping() -> None:
    """Test that the input circuits are empty."""

    with pytest.raises(ValueError, match="Input circuits must not be empty."):
        measure_pauli_strings(
            [],  # type: ignore[arg-type]
            cirq.Simulator(),
            1000,
            1000,
            1000,
            np.random.default_rng(),
        )


def test_invalid_input_circuit_type() -> None:
    """Test that the input circuit type is not frozen circuit"""
    qubits = cirq.LineQubit.range(5)

    qubits_to_pauli: dict[tuple, list[cirq.PauliString]] = {}
    qubits_to_pauli[tuple(qubits)] = [cirq.PauliString({q: cirq.X for q in qubits})]
    with pytest.raises(
        TypeError, match="All keys in 'circuits_to_pauli' must be FrozenCircuit instances."
    ):
        measure_pauli_strings(
            qubits_to_pauli,  # type: ignore[arg-type]
            cirq.Simulator(),
            1000,
            1000,
            1000,
            np.random.default_rng(),
        )


def test_invalid_input_pauli_string_type() -> None:
    """Test input circuit is not mapping to a paulistring"""
    qubits_1 = cirq.LineQubit.range(5)
    qubits_2 = [
        cirq.GridQubit(0, 1),
        cirq.GridQubit(1, 1),
        cirq.GridQubit(1, 0),
        cirq.GridQubit(1, 2),
        cirq.GridQubit(2, 1),
    ]

    circuit_1 = cirq.FrozenCircuit(_create_ghz(5, qubits_1))
    circuit_2 = cirq.FrozenCircuit(_create_ghz(5, qubits_2))

    circuits_to_pauli: dict[cirq.FrozenCircuit, cirq.FrozenCircuit] = {}
    circuits_to_pauli[circuit_1] = [_generate_random_pauli_string(qubits_1)]  # type: ignore
    circuits_to_pauli[circuit_2] = [circuit_1, circuit_2]  # type: ignore

    with pytest.raises(
        TypeError,
        match="All elements in the Pauli string lists must be cirq.PauliString "
        "instances, got <class 'cirq.circuits.frozen_circuit.FrozenCircuit'>.",
    ):
        measure_pauli_strings(
            circuits_to_pauli,  # type: ignore[arg-type]
            cirq.Simulator(),
            1000,
            1000,
            1000,
            np.random.default_rng(),
        )


def test_all_pauli_strings_are_pauli_i() -> None:
    """Test that all input pauli are pauli I"""
    qubits_1 = cirq.LineQubit.range(5)
    qubits_2 = [
        cirq.GridQubit(0, 1),
        cirq.GridQubit(1, 1),
        cirq.GridQubit(1, 0),
        cirq.GridQubit(1, 2),
        cirq.GridQubit(2, 1),
    ]

    circuit_1 = cirq.FrozenCircuit(_create_ghz(5, qubits_1))
    circuit_2 = cirq.FrozenCircuit(_create_ghz(5, qubits_2))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit_1] = [
        cirq.PauliString({q: cirq.I for q in qubits_1}),
        cirq.PauliString({q: cirq.X for q in qubits_1}),
    ]
    circuits_to_pauli[circuit_2] = [cirq.PauliString({q: cirq.X for q in qubits_2})]

    with pytest.raises(
        ValueError,
        match="Empty Pauli strings or Pauli strings consisting "
        "only of Pauli I are not allowed. Please provide "
        "valid input Pauli strings.",
    ):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, np.random.default_rng()
        )


def test_zero_pauli_repetitions() -> None:
    """Test that the pauli repetitions are zero."""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [cirq.PauliString({q: cirq.X for q in qubits})]
    with pytest.raises(ValueError, match="Must provide non-zero pauli_repetitions."):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 0, 1000, 1000, np.random.default_rng()
        )


def test_negative_num_random_bitstrings() -> None:
    """Test that the number of random bitstrings is smaller than zero."""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [cirq.PauliString({q: cirq.X for q in qubits})]
    with pytest.raises(ValueError, match="Must provide zero or more num_random_bitstrings."):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, -1, np.random.default_rng()
        )


def test_zero_readout_repetitions() -> None:
    """Test that the readout repetitions is zero."""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [cirq.PauliString({q: cirq.X for q in qubits})]
    with pytest.raises(
        ValueError, match="Must provide non-zero readout_repetitions for readout" + " calibration."
    ):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 0, 1000, np.random.default_rng()
        )


def test_rng_type_mismatch() -> None:
    """Test that the rng is not a numpy random generator or a seed."""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [cirq.PauliString({q: cirq.X for q in qubits})]
    with pytest.raises(ValueError, match="Must provide a numpy random generator or a seed"):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, "test"  # type: ignore[arg-type]
        )


def test_pauli_type_mismatch() -> None:
    """Test that the input paulis are not a sequence of PauliStrings."""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    circuits_to_pauli: dict[cirq.FrozenCircuit, int] = {}
    circuits_to_pauli[circuit] = 1
    with pytest.raises(
        TypeError,
        match="Expected all elements to be either a sequence of PauliStrings or sequences of"
        " ops.PauliStrings. Got <class 'int'> instead.",
    ):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, "test"  # type: ignore[arg-type]
        )


def test_group_paulis_are_not_qwc() -> None:
    """Test that the group paulis are not qwc."""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    pauli_str1: cirq.PauliString = cirq.PauliString({qubits[0]: cirq.X, qubits[1]: cirq.Y})
    pauli_str2: cirq.PauliString = cirq.PauliString({qubits[0]: cirq.Y})

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [[pauli_str1, pauli_str2]]  # type: ignore
    with pytest.raises(
        ValueError, match="The group of Pauli strings are not Qubit-Wise Commuting with each other."
    ):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, np.random.default_rng()
        )


def test_empty_group_paulis_not_allowed() -> None:
    """Test that the group paulis are empty"""
    qubits = cirq.LineQubit.range(5)

    circuit = cirq.FrozenCircuit(_create_ghz(5, qubits))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[cirq.PauliString]] = {}
    circuits_to_pauli[circuit] = [[]]  # type: ignore
    with pytest.raises(ValueError, match="Empty group of Pauli strings is not allowed"):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, np.random.default_rng()
        )


def test_group_paulis_type_mismatch() -> None:
    """Test that the group paulis type is not correct"""
    qubits_1 = cirq.LineQubit.range(3)
    qubits_2 = [
        cirq.GridQubit(0, 1),
        cirq.GridQubit(1, 1),
        cirq.GridQubit(1, 0),
        cirq.GridQubit(1, 2),
        cirq.GridQubit(2, 1),
    ]
    qubits_3 = cirq.LineQubit.range(8)

    circuit_1 = cirq.FrozenCircuit(_create_ghz(3, qubits_1))
    circuit_2 = cirq.FrozenCircuit(_create_ghz(5, qubits_2))
    circuit_3 = cirq.FrozenCircuit(_create_ghz(8, qubits_3))

    circuits_to_pauli: dict[cirq.FrozenCircuit, list[list[cirq.PauliString]]] = {}
    circuits_to_pauli[circuit_1] = [
        _generate_qwc_paulis(
            _generate_random_pauli_string(qubits_1, enable_coeff=True, allow_pauli_i=False), 6
        )
        for _ in range(3)
    ]
    circuits_to_pauli[circuit_2] = [_generate_random_pauli_string(qubits_2, True) for _ in range(3)]
    circuits_to_pauli[circuit_3] = [_generate_random_pauli_string(qubits_3, True) for _ in range(3)]

    with pytest.raises(
        TypeError,
        match="Expected all elements to be sequences of ops.PauliString, "
        "but found <class 'cirq.ops.pauli_string.PauliString'>.",
    ):
        measure_pauli_strings(
            circuits_to_pauli, cirq.Simulator(), 1000, 1000, 1000, np.random.default_rng()
        )


def test_process_pauli_measurement_results_raises_error_on_missing_calibration() -> None:
    """Test that the function raises an error if the calibration result is missing."""
    qubits: Sequence[cirq.Qid] = cirq.LineQubit.range(5)

    measurement_op = cirq.measure(*qubits, key='m')
    test_circuits: list[cirq.Circuit] = [_create_ghz(5, qubits) + measurement_op for _ in range(3)]

    pauli_strings = [_generate_random_pauli_string(qubits, True) for _ in range(3)]
    sampler = cirq.Simulator()

    circuit_results = sampler.run_batch(test_circuits, repetitions=1000)

    pauli_strings_qubits = sorted(
        set(itertools.chain.from_iterable(ps.qubits for ps in pauli_strings))
    )
    empty_calibration_result_dict = {tuple(pauli_strings_qubits): None}

    with pytest.raises(
        ValueError,
        match="Readout mitigation is enabled, but no calibration result was found for qubits",
    ):
        _process_pauli_measurement_results(
            qubits,
            [pauli_strings],
            circuit_results[0],
            empty_calibration_result_dict,  # type: ignore[arg-type]
            1000,
            1.0,
        )
