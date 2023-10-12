import re

class ModRevModel:
    def __init__(self):
        # Initialize the model attributes (e.g., nodes, edges, etc.)
        self.nodes = []
        self.edges = []
        self.functions = []

    def add_node(self, node):
        self.nodes.append(node)

    def add_edge(self, source, target, value):
        self.edges.append((source, target, value))

    def add_function(self, function_type, node, *args):
        self.functions.append((function_type, node, args))

    def show_state(self):
        """Print the current state of the model"""
        print("Nodes:")
        for node in self.nodes:
            print(node)

        print("\nEdges:")
        for edge in self.edges:
            print(edge)

        print("\nFunctions:")
        for function in self.functions:
            print(function)


def load(filename):
    # Load the MOD_REV model from a file
    with open(filename, "r") as file:
        data = file.read()

    # Parse the data and create a ModRevModel instance
    model = ModRevModel()

    # Populate the model with the parsed data (nodes, edges, etc.)
    vertex_pattern = re.compile(r"vertex\((\w+)\).")
    edge_pattern = re.compile(r"edge\((\w+),(\w+),(\d)\).")
    function_pattern = re.compile(r"function(\w+)\((\w+),(.+?)\).")

    for match in vertex_pattern.finditer(data):
        node = match.group(1)
        model.add_node(node)

    for match in edge_pattern.finditer(data):
        source, target, value = match.groups()
        model.add_edge(source, target, int(value))

    for match in function_pattern.finditer(data):
        function_type, node, args = match.groups()
        args = tuple(map(str.strip, args.split(',')))
        model.add_function(function_type, node, *args)

    return model


def save(model, filename):
    with open(filename, "w") as file:
        # Write vertices
        for node in model.nodes:
            file.write(f"vertex({node}).\n")

        # Write edges
        for source, target, value in model.edges:
            file.write(f"edge({source},{target},{value}).\n")

        # Write functions
        for function_type, node, args in model.functions:
            args_str = ",".join(args)
            file.write(f"function{function_type}({node},{args_str}).\n")
