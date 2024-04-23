from colomoto_jupyter.sessionfiles import new_output_file
import subprocess, json

from ginsim.gateway import japi
import biolqm


def reduce_to_prime_implicants(lqm):
    # BioLQM.ModRevExport outputs the prime implicants
    exported_model_file = save(lqm)
    print(f"Exported model to {exported_model_file}")
    return biolqm.load(exported_model_file, "lp")


def save(model, format="lp"):
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

    def get_nodes(self):
        return [node.toString() for node in self.lqm.getComponents()]

    def _save_model_to_modrev_file(self):
        """
        Saves the current model to a file in modrev format
        """
        self.modrev_file = save(self.lqm)
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

    def check_valid_observation(self, obs):
        """
        Checks if the observation is valid
        """
        core_nodes = self.get_nodes()
        if isinstance(obs, list) and len(obs) > len(core_nodes):
            raise Exception(f"Observation size invalid: {len(core_nodes)}")
        if isinstance(obs, dict):
            for elem in obs.keys():
                if elem not in core_nodes:
                    raise Exception(f"Observation node invalid: {elem}")

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
        self.check_valid_observation(obs)
        self.dirty_flag = True
        if not name:
            name = f"observation_{len(self.observations.keys()) + 1}"
        self.observations[name] = obs

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

        for key, value in observations_dict.items():
            self.check_valid_observation(value)

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
            raise Exception(f"Error running modrev: {result}")

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

    def parse_new_function(self, new_function):

        print(f"New function: {new_function}")

        function_terms = new_function.split("||")
        function_elements = []
        for i, term in enumerate(function_terms):
            function_elements.append(term.split("&&"))

        print(f"Function terms: {function_terms}")
        print(f"Function elements: {function_elements}")

        parsed_terms = [[item.strip().replace('(', '').replace(')', '')]
                        for sublist in function_elements for item in sublist]

        print(f"Clean data: {parsed_terms}")

        return parsed_terms

    def compute_new_function(self, core_nodes, core_functions, target_node, new_function):

        # FIXME, manager not workings
        # NOTE WE COULD JUST WRITE THE LQM FILE TO DISK, EDIT THE .lp FILE AND LOAD

        OperandFactory = japi.java.jvm.org.colomoto.mddlib.logicalfunction.SimpleOperandFactory
        operandFactory = OperandFactory(core_nodes)
        manager = operandFactory.getMDDManager()

        print(f"OperandFactory: {operandFactory}")
        print(f"Manager: {manager}")

        try:
            i = core_nodes.index(target_node)
            print(f"Target node: {target_node}, index: {i}")

        except ValueError:
            print(f"The value {target_node} is not in the list.")
            return

        print(f"Repairing {target_node} with {new_function}")

        parsed_terms = self.parse_new_function(new_function)
        print(f"Parsed terms: {parsed_terms}")

        # compute new mdd
        ExpressionStack = japi.java.jvm.org.colomoto.biolqm.io.antlr.ExpressionStack
        stack = ExpressionStack(operandFactory)
        stack.clear()

        for term_index in range(len(parsed_terms)):
            num_nodes = 0
            for element_index in range(len(parsed_terms[term_index])):
                stack.ident(parsed_terms[term_index][element_index])
                num_nodes += 1

                if num_nodes > 1:
                    OperatorAnd = japi.java.jvm.org.colomoto.biolqm.io.antlr.Operator.AND
                    stack.operator(OperatorAnd)

        if len(parsed_terms) > 1:
            OperatorOr = japi.java.jvm.org.colomoto.biolqm.io.antlr.Operator.OR
            total_terms = len(parsed_terms)
            while total_terms > 1:
                stack.operator(OperatorOr)
                total_terms -= 1

        fn = stack.done()
        core_functions[i] = fn.getMDD(manager)

        return core_functions

    def _repair_option_1(self, repair_action):
        """
        Option 1: Create new LQM model based on editing the MDD and functions directly.
        """
        target_node = repair_action.split("@")[0]  # v1
        function_id = (repair_action.split("@")[1]).split(",")[0]  # F1
        new_function = (repair_action.split("@")[1]).split(",")[1]  # (v2) || (v3)

        core_nodes = self.lqm.getComponents()
        core_functions = self.lqm.getLogicalFunctions()
        ddmanager = self.lqm.getMDDManager()
        print(f"Core nodes: {core_nodes}")
        print(f"Core node 0: {core_nodes[0]}")
        print(f"Core functions: {core_functions}")
        print(f"DD Manager: {ddmanager}")

        print("Computing new function")
        core_functions = self.compute_new_function(core_nodes, core_functions, target_node, new_function)

        LogicalModelImpl = japi.java.jvm.org.colomoto.biolqm.LogicalModelImpl
        new_lqm = LogicalModelImpl(core_nodes, ddmanager, core_functions)

        return ModRev(new_lqm)

    def _repair_option_2(self, repair_action):
        """
        Option 2: Write the model to the file and load it
        """
        target_node = repair_action.split("@")[0]  # v1
        function_id = (repair_action.split("@")[1]).split(",")[0]  # F1
        new_function = (repair_action.split("@")[1]).split(",")[1]  # (v2) || (v3)

        new_lines = []
        with open(self.modrev_file, "r") as f:
            # find all instances of functionOr(target_node, _)
            #   and functionAnd(target_node, _, _)
            #   and delete them

            for line in f.readlines():
                if not line.startswith(f"functionOr({target_node}") and not line.startswith(
                        f"functionAnd({target_node}"):
                    new_lines.append(line)

            parsed_function = self.parse_new_function(new_function)

            # and then go to the append functionOr(target_node, 1..x)
            Or = f"..{len(parsed_function)}" if len(parsed_function) > 1 else ""
            new_lines.append(f"functionOr({target_node},1{Or}).\n")

            for term_index in range(len(parsed_function)):
                for elem in parsed_function[term_index]:
                    new_lines.append(f"functionAnd({target_node},{term_index + 1},{elem}).\n")

        filename = new_output_file("lp")
        with open(filename, "w") as f2:
            for line in new_lines:
                f2.write(line)
        print(f"Filename: {filename}")

        new_lqm = biolqm.load(filename)

        new_filename = save(new_lqm)

        print(f"New Filename: {new_filename}")

        return ModRev(new_lqm)

    def add_fixed_nodes(self, fixed_nodes):
        if fixed_nodes is None:
            fixed_nodes = []

        nodes = self.get_nodes()
        for node in fixed_nodes:
            if node not in nodes:
                raise Exception(f"Invalid fixed node: {node}")

        with open(self.modrev_file, 'r') as file:
            lines = file.readlines()

        last_vertex_idx = next((i for i, line in reversed(list(enumerate(lines))) if line.startswith("vertex")))

        for node in fixed_nodes:
            fixed_node = f"fixed({node}).\n"
            if fixed_node not in lines:
                lines.insert(last_vertex_idx + 1, fixed_node)
                self.dirty_flag = True

        with open(self.modrev_file, 'w') as file:
            file.writelines(lines)

    def generate_repairs(self, repair, fixed_nodes=None):

        if not self.repairs[repair]:
            raise Exception("Invalid repair")

        self.add_fixed_nodes(fixed_nodes)

        repair_action = self.repairs[repair]  # v1@F1,(v2) || (v3)

        flag = False
        if flag:
            return self._repair_option_1(repair_action)  # edit lqm directly
        else:
            return self._repair_option_2(repair_action)  # write to file
