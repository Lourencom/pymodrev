import re, subprocess, json, os


# node(id)
class Node:
    def __init__(self, id):
        self.id = id

    def __repr__(self):
        return f"Node({self.id})"


# edge(source, target, weight)
class Edge:
    def __init__(self, source, target, weight):
        self.source = source
        self.target = target
        self.weight = weight

    def __repr__(self):
        return f"Edge({self.source}, {self.target}, {self.weight})"


# functionAnd(source, term, regulator)
class ANDFunction:
    def __init__(self, source, term, regulator):
        self.source = source
        self.term = term
        self.regulator = regulator

    def __repr__(self):
        return f"ANDFunction({self.source}, {self.term}, {self.regulator})"


# functionOr(source, 1..n_terms)
class ORFunction:
    def __init__(self, source, terms):
        self.source = source
        self.terms = terms

    def __repr__(self):
        return f"ORFunction({self.source}, {self.terms})"


class BooleanFunction:
    def __init__(self, source, n_terms):
        self.source = source
        self.terms = [[] for _ in range(n_terms)]

    def add_term_regulator(self, term, regulator):
        real_term = term - 1
        if real_term < 0 or real_term >= len(self.terms):
            raise IndexError("Invalid term index")
        self.terms[real_term].append(regulator)

    def __repr__(self):
        term_expressions = [' and '.join(term) for term in self.terms if term]
        full_expression = ' or '.join(f"({expr})" if expr else "" for expr in term_expressions)

        return f"{self.source} = {full_expression}"


# Dict of nodes with key = node id and value = node object
# Dict of functions with key = node id and value = node_boolean_function
# Dict of edges with key = source and value = dict(target : weight)
class ModRevModel:
    def __init__(self):
        self.nodes = {}
        self.functions = {}
        self.edges = {}

    def __repr__(self):
        node_repr = "Nodes:\n" + "\n".join(f"{node}" for node in self.nodes.values())
        edge_repr = "Edges:\n" + "\n".join(f"{source}->{target}: {weight}"
                                           for source, edges in self.edges.items()
                                           for target, weight in edges.items())
        function_repr = "Functions:\n" + "\n".join(f"{function}"
                                                   for function in self.functions.values())

        return f"{node_repr}\n{edge_repr}\n{function_repr}"

    def add_node(self, node_id):
        if node_id not in self.nodes:
            node = Node(node_id)
            self.nodes[node.id] = node

    def add_edge(self, source, target, weight):
        self.add_node(source)
        self.add_node(target)

        edge = Edge(source, target, weight)

        if source not in self.edges:
            self.edges[source] = {}

        self.edges[source][target] = weight

    # Creates the boolean function that will define the node, after reading functionOr(node, 1..n_terms)
    def create_boolean_function(self, node_id, n_terms):
        if node_id not in self.nodes:
            raise ValueError(f"Invalid node id when processing functionOr{node_id, n_terms}")

        function = BooleanFunction(node_id, n_terms)

        self.functions[node_id] = function

    # Adds a term to the boolean function of a node, after reading functionAnd(node, term, regulator)
    def update_boolean_function(self, node_id, term, regulator):
        if (node_id or regulator) not in self.nodes:
            raise ValueError(f"Invalid node id or regulator when processing functionAnd{node_id, term, regulator}")

        self.functions[node_id].add_term_regulator(term, regulator)

    def get_boolean_function(self, node_id):
        return self.functions[node_id]

    def load_from_file(self, filename):
        with open(filename, 'r') as file:
            for line in file:
                # Process vertices
                for match in re.finditer(r'vertex\((.+?)\)', line):
                    node_id = match.group(1)
                    self.add_node(node_id)

                # Process edges
                for match in re.finditer(r'edge\((.+?),(.+?),(.*?)\)', line):
                    source, target, weight = match.groups()
                    self.add_edge(source, target, int(weight))

                # Process functionOr(source, 1..n_terms)
                for match in re.finditer(r'functionOr\((.+?),1\.\.(.*?)\)', line):
                    node_id, n_terms = match.groups()
                    self.create_boolean_function(node_id, int(n_terms))

                # Process functionAnd
                for match in re.finditer(r'functionAnd\((.+?),(.*?),(.*?)\)', line):
                    node_id, term, regulator = match.groups()
                    self.update_boolean_function(node_id, int(term), regulator)

    def save_to_file(self, filename):
        with open(filename, 'w') as file:
            # Write vertices
            for node in self.nodes.values():
                file.write(f"vertex({node.id}).")

            file.write("\n")

            # Write edges
            for source, edges in self.edges.items():
                for target, weight in edges.items():
                    file.write(f"edge({source},{target},{weight}).\n")

            # Write functions
            for function in self.functions.values():
                n_terms = len(function.terms)
                file.write(f"functionOr({function.source},1..{n_terms}).\n")

                for term in range(len(function.terms)):
                    for regulator in function.terms[term]:
                        file.write(f"functionAnd({function.source},{term + 1},{regulator}). ")

                file.write("\n")


def run_modrev(filename, obs_file=None, check_consistency=False, verbose=2):
    # load absolute path to modrev executable
    modrev_path = os.path.join(os.path.dirname(__file__), "../examples/ModRev/src/modrev")
    command = [modrev_path, "-m", filename]

    if obs_file:
        command.extend(["-obs", obs_file])

    if check_consistency:
        command.append("-cc")

    command.extend(["-v", str(verbose)])
    print(command)
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout


def check_consistency(filename, obs_file=None):
    json_output = run_modrev(filename, obs_file, check_consistency=True)

    try:
        data = json.loads(json_output)
        consistent = data["consistent"]
        inconsistencies = data.get("inconsistencies", [])

        if consistent:
            return "This network is Consistent!"
        else:
            return "This network is Inconsistent."

    except json.JSONDecodeError:

        # Handle cases where the output is not in JSON format
        raise ValueError("Output is not in valid JSON format")


def check_possible_repair(filename, obs_file=None):
    output = run_modrev(filename, obs_file, verbose=0)

    if "not possible" in output:
        return "Not possible to repair network for now."

    match = re.search(r'(\w+)@F,(.+)', output)
    if match:
        node, repair_function = match.groups()
        return f"Node {node} can be repaired with function: {repair_function}"


if __name__ == "__main__":
    model = ModRevModel()
    model.load_from_file("../examples/model.lp")
    print(model)
    print(check_consistency("../examples/model.lp", "../examples/obsTS02.lp"))
    print(check_possible_repair("../examples/model.lp", "../examples/obsTS02.lp"))