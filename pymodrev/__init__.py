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
    components = lqm.getComponents()
    int_class = japi.java.jvm.int
    new_functions = japi.java.new_array(int_class, len(components))

    for i in range(len(core_functions)):
        function = core_functions[i]
        print("------------------------------")
        print(f"Component: {components[i]}")
        print(f"Function: {bin(function)}")

        # for now lets say our target value is 1
        formula = formulas.getPrimes(function, 1)
        print("Reduced formula: ", formula.toString())
        function_reduced = formula.toArray()

        simplified_terms = []
        for term_array in function_reduced:
            term_elements = []
            for term_index in range(len(term_array)):
                element = f"{components.get(formula.regulators[term_index]).getNodeID()}"
                if term_array[term_index] == 0:
                    term_elements.append( "!" + element)
                elif term_array[term_index] == 1:
                    term_elements.append(element)
            term = "(" + " && ".join(term_elements) + ")"
            simplified_terms.append(term)

        final_simplified_function = " || ".join(simplified_terms)
        print(f"Final simplified function: {final_simplified_function}")

        for i in range(formula.getTerms().get(0).getNumVars()):
            print(f"Regulator {i}: {components.get(formula.regulators[i]).getNodeID()}")

        # TODO: insert new formula in the mdd
        #new_functions[i] = function_reduced

    LogicalModelImpl_class = japi.java.jvm.org.colomoto.biolqm.LogicalModelImpl
    new_lqm = LogicalModelImpl_class(components, dd_manager, new_functions)

    return new_lqm


def save(model, format=None):
    filename = new_output_file(format)
    return biolqm.save(model, filename, format)


class ModRev:
    modrev_path = "/opt/ModRev/modrev"

    def __init__(self, lqm):
        self.dirty_flag = None
        self.modrev_file = None
        self.lqm = lqm  # bioLQM model JavaObject
        self.prime_impl = reduce_to_prime_implicants(lqm)
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
        if self.dirty_flag:
            self._save_model_to_modrev_file()

        result = self._run_modrev('-m', self.modrev_file, '-obs', self.obs_to_modrev_format(), '-v', '0', '-cc')

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
        if self.dirty_flag:
            self._save_model_to_modrev_file()

        result = self._run_modrev('-m', self.modrev_file, '-obs', self.obs_to_modrev_format(), '-v', '0')

        if not result or result.returncode != 0:
            print(f"Error running modrev: {result}")
            return

        # output of modrev comes in format:
        # change function to v1 = v2 || v3
        # v1@F1,(v2) || (v3)
        output_lines = result.stdout.split("\n")
        print("Possible repairs:")
        for line in output_lines:
            key = len(self.repairs.keys())
            self.repairs[key] = line
            print(f"Repair {key}: {line}")
        return self.repairs

    def generate_repairs(self, repair):
        """
        Generates a list of fixed lqm models (as JavaObjects)
        """
        if not self.repairs[repair]:
            print("Invalid repair")
            return
        # v1@F1,(v2) || (v3)
        repair_action = self.repairs[repair]
        target_node = repair_action.split("@")[0]
        new_function = repair_action.split("@")[1]
        print(f"Repairing {target_node} with {new_function}")

        # clones the lqm model
        cloned_lqm = self.lqm.clone()

        # TODO: apply repair on cloned_lqm,
        #    editing the mdd functions directly
        # returns all the generated models in the repair process
