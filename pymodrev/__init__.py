from colomoto_jupyter.sessionfiles import new_output_file
from py4j.java_gateway import JavaGateway, GatewayParameters, JavaObject
import subprocess, json, os

from ginsim.gateway import japi
import biolqm


def reduce_to_prime_implicants(lqm):
    # japi.java is gateway
    if not isinstance(lqm, JavaObject):
        raise ValueError("Expected a JavaObject")

    dd_manager = lqm.getMDDManager()
    core_functions = lqm.getLogicalFunctions()

    MDD2PrimeImplicants_class = japi.java.jvm.org.colomoto.biolqm.helper.implicants.MDD2PrimeImplicants
    formulas = MDD2PrimeImplicants_class(dd_manager)
    new_formulas = []
    components = lqm.getComponents()

    for i in range(len(core_functions)):
        node = components.get(i)
        function = core_functions[i]

        formula = formulas.reduceToPrimeImplicants(function, node)
        new_formulas.append(formula)

    LogicalModelImpl_class = japi.java.jvm.org.colomoto.biolqm.LogicalModelImpl
    new_lqm = LogicalModelImpl_class(components, dd_manager, new_formulas)

    return new_lqm


def save(model, format=None):
    filename = new_output_file(format)
    return biolqm.save(model, filename, format)


class ModRev:
    modrev_path = "/opt/ModRev/modrev"

    def __init__(self, lqm):
        self.lqm = lqm  # bioLQM model JavaObject
        # self.prime_impl = reduce_to_prime_implicants(lqm)
        self._save_model_to_modrev_file()
        self.observations = {}
        self.repairs = {}

    def _save_model_to_modrev_file(self):
        """
        Saves the current model to a file in modrev format
        """
        self.modrev_file = save(self.lqm, "lp")
        self.dirty_flag = False

    def _run_modrev(self, *args):
        """
        Runs modrev with the given arguments
        """
        try:
            result = subprocess.run(
                [self.modrev_path] + list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return result
        except Exception as e:
            print(f"Error running modrev: {e}")
            return None

    def _expand_observations_recursively(self, current_profile, current_nodes, path=[]):
        expanded_observations = {}
        has_wildcard = False

        for node, value in current_nodes.items():
            if value == '*':
                has_wildcard = True
                for replacement_value in (0, 1):
                    # Clone the current nodes and replace '*' with 0 or 1
                    new_nodes = current_nodes.copy()
                    new_nodes[node] = replacement_value
                    new_path = path + [(node, replacement_value)]
                    expanded_observations.update(
                        self._expand_observations_recursively(current_profile, new_nodes, new_path))
                break  # Exit the loop after handling the first wildcard

        if not has_wildcard:
            # Generate a unique profile name based on the path of replacements
            new_profile_name = current_profile + ''.join([f"_{node}_{value}" for node, value in path])
            expanded_observations[new_profile_name] = current_nodes

        return expanded_observations

    def _expand_observations(self):
        expanded_observations = {}
        for profile, nodes in self.observations.items():
            expanded_observations.update(self._expand_observations_recursively(profile, nodes))
        return expanded_observations

    def obs_to_modrev_format(self):
        expanded_observations = self._expand_observations()

        observation_filename = new_output_file("lp")

        with open(observation_filename, 'w') as file:
            for profile, nodes in expanded_observations.items():
                file.write(f"exp({profile})\n")

                for node, value in nodes.items():
                    file.write(f"obs({profile}, {node.lower()}, {value})\n")

        print(f"Observations were successfully written to {observation_filename}")
        return observation_filename

    def add_obs(self, obs, name=None):
        """
        Adds an observation to the dict
        # Example dictionary of observations
        observations = {
            "obs_1": [0, 1, "*", 1, 0],  # Example ModelState as a list
            "obs_2": {"node1": 0, "node2": 1, "node3": "*", "node4": 1, "node5": 0}  # As a dict
        }
        :param obs:
        :param name:
        :return:
        """
        self.dirty_flag = True
        if not name:
            name = f"observation_{len(self.observations.keys()) + 1}"
        self.observations[name] = obs

    def is_consistent(self):
        """
        Checks if the current state of the model is consistent
        """
        # TODO: needs to take into account observations
        if self.dirty_flag:
            self._save_model_to_modrev_file()

        with open(self.modrev_file, "r") as f:
            print(f.readlines())

        result = self._run_modrev('-m', self.modrev_file, '-v', '0', '-cc')

        if not result or result.returncode != 0:
            print(f"Error running modrev: {result}")
            return False

        output = json.loads(result.stdout)
        return output.get("consistent", False)

    def remove_obs(self, key):
        """
        Removes an observation from the dict by key
        """
        if key in self.observations:
            self.observations.pop(key)
            self.dirty_flag = True

    def set_obs(self, observations_dict):
        """
        Sets the observation dict
        """
        self.observations = observations_dict
        self.dirty_flag = True

    def stats(self):
        """
        Shows possible reparation actions in a friendly manner
        """
        # TODO: needs to take into account observations
        if self.dirty_flag:
            self._save_model_to_modrev_file()

        result = self._run_modrev('-m', self.modrev_file, '-v', '0')

        if not result or result.returncode != 0:
            print(f"Error running modrev: {result}")
            return

        # output of modrev comes in format:
        # v1@F1,(v2) || (v3)
        # change function to v1 = v2 || v3
        output_lines = result.stdout.split("\n")
        print("Possible repairs:")
        for line in output_lines:
            key = len(self.repairs.keys())
            self.repairs[key] = line
            print(f"Repair {key}: {line}")

    def generate_repairs(self, repair):
        """
        Generates a list of fixed lqm models (as JavaObjects)
        """
        if not self.repairs[repair]:
            print("Invalid repair")
            return

        # clones the lqm model
        cloned_lqm = self.lqm.clone()

        # todo: apply repair on cloned_lqm
        # returns all the generated models in the repair process
