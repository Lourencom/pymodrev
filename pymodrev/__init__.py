from colomoto_jupyter.sessionfiles import new_output_file
import subprocess, json

from ginsim.gateway import japi
import biolqm


def reduce_to_prime_implicants(lqm):
    # BioLQM.ModRevExport outputs the prime implicants
    exported_model_file = save(lqm)
    return biolqm.load(exported_model_file, "lp")


def save(model, format="lp"):
    filename = new_output_file(format)
    return biolqm.save(model, filename, format)


class ModRev:
    modrev_path = "/opt/ModRev/modrev"

    def __init__(self, lqm):
        self.dirty_flag = None
        self.modrev_file = None
        self.observation_file = None
        self.lqm = lqm  # bioLQM model JavaObject
        self._lowercase_all_nodes() # hacky fix for now, we will lowercase all nodes
        self.prime_impl = reduce_to_prime_implicants(lqm)
        self._save_model_to_modrev_file()
        self.observations = {}
        self.repairs = {}

    def print(self):
        """
        Reads the model from a file
        """
        with open(self.modrev_file, 'r') as file:
            print(file.read())

    def get_nodes(self):
        return [node.toString() for node in self.lqm.getComponents()]

    def get_observations(self):
        return self.observations

    def _save_model_to_modrev_file(self):
        """
        Saves the current model to a file in modrev format
        """
        self.modrev_file = save(self.lqm)
        self.dirty_flag = False
        # FIXME: just a reminder, in the java code of bioLQM, the model is always generating edges with value 1,
        #  even when they are exported with value 0.

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

        self.observation_file = observation_filename
        return observation_filename

    def _lowercase_all_nodes(self):
        """
        Lowercases all nodes in the model
        """
        for node in self.lqm.getComponents():
            node.setName(node.getName().lower())
            node.setNodeID(node.getNodeID().lower())

    def is_consistent(self):
        """
        Checks if the current state of the model is consistent
        """
        if self.dirty_flag:
            self._save_model_to_modrev_file()

        result = self._run_modrev('-m', self.modrev_file, '-obs', self.obs_to_modrev_format(), '-v', '0', '-cc')

        if not result or result.returncode != 0:
            raise Exception(f"Error running modrev: {result}")

        output = json.loads(result.stdout)
        return output.get("consistent", False)

    def convert_obs_to_dict(self, obs):
        """
        Converts an observation to a dictionary
        """
        if isinstance(obs, list):
            obs = {self.get_nodes()[i]: obs[i] for i in range(len(obs))}
        return obs

    def check_valid_observation(self, obs):
        """
        Checks if the observation is valid
        """
        core_nodes = self.get_nodes()
        if not isinstance(obs, list) and not isinstance(obs, dict):
            raise Exception("Observation must be a list or a dictionary")
        elif isinstance(obs, list) and len(obs) > len(core_nodes):
            raise Exception(f"Observation size invalid: {len(obs)}. Should be at most {len(core_nodes)}.")
        elif isinstance(obs, dict):
            for elem in obs.keys():
                if elem not in core_nodes:
                    raise Exception(f"Observation node invalid: {elem}")

        return self.convert_obs_to_dict(obs)

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
        print(self.get_nodes())
        new_obs = self.check_valid_observation(obs)
        self.dirty_flag = True
        if not name:
            name = f"observation_{len(self.observations.keys()) + 1}"
        self.observations[name] = new_obs

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
        if not isinstance(observations_dict, dict):
            raise Exception("Observations must be a dictionary")

        new_dict = {}
        for key, value in observations_dict.items():
            new_dict[key] = self.check_valid_observation(value)

        self.observations = new_dict
        self.dirty_flag = True

    def stats(self, observation_file=None, state_scheme=None):
        """
        Shows possible reparation actions in a friendly manner
        """
        if self.dirty_flag:
            self._save_model_to_modrev_file()

        obs = observation_file if observation_file else self.obs_to_modrev_format()

        if state_scheme is None:
            result = self._run_modrev('-m', self.modrev_file, '-obs', obs, '-v', '0')
        elif state_scheme == "steady":
            result = self._run_modrev('-m', self.modrev_file, '-obs', obs, '-ot',  'ss', '-v', '0')
        elif state_scheme == "synchronous":
            if obs == self.obs_to_modrev_format():
                raise Exception("Time-series observations not implemented yet in python."
                                "Pass an observation file with observation_file=...")
            else:
                result = self._run_modrev('-m', self.modrev_file, '-obs', obs, '-v', '0', '-up', 's')
        else:
            raise Exception("Invalid state scheme")

        # FIXME: this a temporary hardcode for testing purposes
        # result = self._run_modrev('-m', '/opt/ModRev/examples/model.lp', '-obs', '/opt/ModRev/examples/obsTS01.lp', '-up', 's', '-v', '0')

        if not result or result.returncode != 0:
            raise Exception(f"Error running modrev: {result}")

        # output of modrev comes in format:
        # change function to v1 = v2 || v3
        # v1@F1,(v2) || (v3)
        # repair: v2@E,v1,v2:F,(v1 && v3);E,v3,v2:F,(v1 && v3)
        output = result.stdout.strip("\n")
        inconsistent_nodes = output.split("/")  # [v2@E,v1,v2:F,(v1 && v3);E,v3,v2:F,(v1 && v3)]

        if "not possible" in output or "consistent" in output:
            print(output)
            return

        for node in inconsistent_nodes:
            target_node, node_repairs = node.split("@")
            repair_options = node_repairs.split(";")
            print(f"Inconsistent node: {target_node}")
            print(f"Repair options: {repair_options}")
            self.repairs[target_node] = repair_options

    def decompose_function(self, new_function):
        """
        Receives a function and decomposes it into its elements

        Example:
        :param new_function: (v2 && v1) || (v3)
        :return: [['v2', 'v1'], ['v3']]
        """

        print(f"New function: {new_function}")

        function_terms = new_function.split("||")
        function_elements = []
        for i, term in enumerate(function_terms):
            function_elements.append(term.split("&&"))

        print(f"Function terms: {function_terms}")
        print(f"Function elements: {function_elements}")

        parsed_terms = []

        for term in function_elements:
            if len(term) == 1:  # simple term
                parsed_terms.append([term[0].strip().replace('(', '').replace(')', '')])
                continue

            parsed_terms.append([elem.strip().replace('(', '').replace(')', '') for elem in term])

        print(f"Clean data: {parsed_terms}")

        return parsed_terms

    def parse_new_function(self, new_function, target_node):
        """
        Decompose the function, and convert it to writeable modrev format.

        Example:
        :param new_function: (v2 && v1) || (v3)
        :param target_node: v1
        :return: ['functionOr(v1,1..2).', 'functionAnd(v1,1,v2).', 'functionAnd(v1,1,v1).', 'functionAnd(v1,2,v3).']
        """
        decomposed_function = self.decompose_function(new_function)
        return self.convert_terms_to_functions(decomposed_function, target_node)

    def convert_terms_to_functions(self, terms, target_node):
        """
        Converts the terms to writeable modrev format

        Example:
        :param terms: [['v2'], ['v3']]
        :param target_node: v1
        :return: ['functionOr(v1,1..2).', 'functionAnd(v1,1,v2).', 'functionAnd(v1,2,v3).']
        """
        num_terms = len(terms)

        writeable_functions = []

        Or = f"..{num_terms}" if num_terms > 1 else ""
        OrFunction = f"functionOr({target_node},1{Or}).\n"
        writeable_functions.append(OrFunction)

        for term_index in range(len(terms)):
            for elem in terms[term_index]:
                AndFunction = f"functionAnd({target_node},{term_index + 1},{elem}).\n"
                writeable_functions.append(AndFunction)

        return writeable_functions

    def change_function(self, repair, target_node):
        # F1,(v2) || (v3)
        changed_function = repair.split(",")[1]
        return self.parse_new_function(changed_function, target_node)

    def flip_edge(self, repair):
        # E,v1,v2
        elems = repair.split(",")
        new_edge = f"edge({elems[1]},{elems[2]})."
        return new_edge

    def add_edge(self, repair):
        # A,v1,v2,1
        elems = repair.split(",")
        new_edge = f"edge({elems[1]},{elems[2]},{elems[3]}).\n"
        return new_edge

    def convert_repair_operation(self, repair_operation, target_node):
        """
        Returns the repair as a string
        """
        # repair: v2@E,v1,v2:F,(v1 && v3);E,v3,v2:F,(v1 && v3)
        if repair_operation.startswith("F"):  # if repair is F, ... we change function
            return self.change_function(repair_operation, target_node)
        elif repair_operation.startswith("E"):  # if repair is E,v1,v2, we flip sign of edge(v1,v2).
            return self.flip_edge(repair_operation)
        elif repair_operation.startswith("A"):  # if repair is A,v1,v2,1 we add edge(v1,v2,1)
            return self.add_edge(repair_operation)
        else:
            raise Exception(f"Repair type does not exist for repair: {repair_operation}")

    def get_repair_steps(self, repair_action):
        """
        Receives a repair action associated with a single repair option of a node,
        which is a string in the modrev output format.
        Example:
        :param repair_action: E,v1,v2:F,(v1 && v3)
        :return: ['E,v1,v2', 'F,(v1 && v3)']
        """
        return repair_action.split(":")

    def write_new_edge(self, repair, lines):
        """
        Repair is a new 'edge(v1,v2,1).', add it to the file to the start of the edge listing.

        :param repair: 'edge(v1,v2,1).'
        :param lines:
        :return:
        """
        first_edge_idx = next((i for i, line in enumerate(lines) if line.startswith("edge")))
        lines.insert(first_edge_idx, repair)

    def write_flip_edge(self, repair, lines):
        """
        Repair is a flipped 'edge(v1,v2).', find the edge(v1,v2) and flip the third element.

        :param repair: 'edge(v1,v2).'
        :param lines:
        :return:
        """
        for i, line in enumerate(lines):
            if line.startswith(repair.split(")")[0]):
                elems = line.split(",")
                old_sign = elems[2].split(")")[0]
                new_sign = 1 if old_sign == "0" else 0
                lines[i] = f"{elems[0]},{elems[1]},{new_sign}).\n"
                break

    def write_new_node_functions(self, repair, lines):
        """
        Repair is a new function for a node, find the functions for the target node and delete them.
        Then write the new functions.

        :param repair: ['functionOr(v1,1..2).\n', 'functionAnd(v1,1,v2).\n', 'functionAnd(v1,2,v3).\n']
        :param lines:
        :return:
        """
        target_node = repair[0].split("(")[1].split(",")[0]

        # Find the functions for the target node and delete them
        possible_matches = ["functionOr(" + target_node, "functionAnd(" + target_node]
        new_lines = [line for line in lines if not any(match in line for match in possible_matches)]

        new_lines.extend(repair)

        lines[:] = new_lines # update the original list

    def apply_repairs(self, repairs, new_filename):
        """
        Writes the repairs given in modrev format to a new file

        Example:
        :param repairs:
        :param new_filename: 'booloo.lp'
        :return:
        """
        print(f"Repairs: {repairs}")

        with open(new_filename, 'r') as file:
            lines = file.readlines()

        for repair in repairs:
            if isinstance(repair, list):  # repair is function change
                self.write_new_node_functions(repair, lines)
            elif repair.startswith("edge") and len(repair.split(",")) == 3:  # repair is a new edge
                self.write_new_edge(repair, lines)
            elif repair.startswith("edge"):  # repair is a flipped edge
                self.write_flip_edge(repair, lines)
            else:
                raise Exception(f"Invalid repair: {repair}")

        with open(new_filename, 'w') as file:
            file.writelines(lines)

    def _repair(self, node, repair_action, repair_file):
        """
        Receives a repair action associated with a single repair option of a node,
        which is a string in the modrev output format.
        Example:
        :param node: v1
        :param repair_action: E,v1,v2:F,(v1 && v3)
        """

        print(f"Repairing node {node} with action: {repair_action}")

        repair_steps = self.get_repair_steps(repair_action)
        converted_repairs = [self.convert_repair_operation(op, node) for op in repair_steps]

        self.apply_repairs(converted_repairs, repair_file)  # writes these to the file
        print(f"Repairs written to {repair_file}")

        new_lqm = biolqm.load(repair_file)
        return ModRev(new_lqm)

    def add_fixed_nodes(self, fixed_nodes, filename):
        if fixed_nodes is None or len(fixed_nodes) == 0:
            return

        nodes = self.get_nodes()
        for node in fixed_nodes:
            if node not in nodes:
                raise Exception(f"Invalid fixed node: {node}")

        with open(filename, 'r') as file:
            lines = file.readlines()

        last_vertex_idx = next((i for i, line in reversed(list(enumerate(lines))) if line.startswith("vertex")))

        for node in fixed_nodes:
            fixed_node = f"fixed({node}).\n"
            if fixed_node not in lines:
                lines.insert(last_vertex_idx + 1, fixed_node)
                self.dirty_flag = True

        with open(filename, 'w') as file:
            file.writelines(lines)

    def create_and_write_to_new_file(self, fixed_nodes=None):
        """
        Creates a new file with the current model and returns the filename
        """
        new_filename = new_output_file("lp")
        with open(self.modrev_file, 'r') as file:
            lines = file.readlines()
        with open(new_filename, 'w') as file:
            file.writelines(lines)

        self.add_fixed_nodes(fixed_nodes, new_filename)

        return new_filename

    def generate_repairs(self, repair_options, fixed_nodes=None):
        """
        Generates the repaired models.
        repair_options is a dictionary with the following format:
        {'node': repair_option, ...}
        and repair_option is a simple integer, associated with the repair option to be used.

        :param repair_options:
        :param fixed_nodes:
        :return:
        """
        for node, option in repair_options.items():
            if not self.repairs[node]:
                raise Exception("Invalid repair node")

            if not self.repairs[node][option]:
                raise Exception("Invalid repair option")

        new_file = self.create_and_write_to_new_file(fixed_nodes)

        repaired_models = []
        for node, repair_action in repair_options.items():
            repaired_models.append(self._repair(node, self.repairs[node][repair_action], new_file))

        return repaired_models[-1]
