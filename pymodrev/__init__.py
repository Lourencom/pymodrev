from py4j.java_gateway import JavaGateway, GatewayParameters, JavaObject
import subprocess, json, os
from colomoto_jupyter.sessionfiles import new_output_file

from ginsim.gateway import japi


def save(model, filename, format=None):
    assert japi.lqm.save(model, filename, format)
    return filename


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


class ModRev:
    modrev_path = "/home/lourenco/research/colomoto/ModRev/src/modrev"

    def __init__(self, lqm):
        self.lqm = lqm  # bioLQM model JavaObject

        self.prime_impl = reduce_to_prime_implicants(lqm)

        # file with lqm model in modrev format
        # fixme: format "lp" must come in the bioLQM dependency in colomoto-docker/jupyter
        modrev_file = new_output_file("lp")
        self.modrev_file = save(self.lqm, modrev_file, "lp")

        self.dirty_flag = False  # bool to indicate if the object has been modified
        self.obs_dict = {}  # dict to store observations

    def add_obs(self, *args, **kwargs):
        """
        Adds observations to the model. This function can handle a single observation
        with an optional label, or a dictionary of observations.

        Usage:
        - add_obs(observation, name="some_label")
        - add_obs({"label1": observation1, "label2": observation2})
        """

        # If the first argument is a dictionary, we assume it's a bulk addition of observations.
        if len(args) == 1 and isinstance(args[0], dict):
            for name, obs in args[0].items():
                self._add_single_observation(obs, name)

        # If there are two arguments, we assume it's a single observation with a label.
        elif len(args) == 1 and 'name' in kwargs:
            self._add_single_observation(args[0], kwargs['name'])

        # If there's only one argument without a name, it's a single unnamed observation.
        elif len(args) == 1:
            self._add_single_observation(args[0], name=None)

        # Otherwise, it's an error.
        else:
            raise ValueError("Invalid arguments for add_obs.")

    def _add_single_observation(self, obs, name=None):
        """
        Private helper method to add a single observation to the model.
        """
        # Update dirty flag and observations dictionary
        self.dirty_flag = True
        if name:
            self.obs_dict[name] = obs
        else:
            # Handle unnamed observation
            self.obs_dict[f"observation_{len(self.obs_dict) + 1}"] = obs

    def is_consistent(self):
        """
        Checks if the current state of the model is consistent
        """
        # saves lqm model onto file
        # fixme: needs to take into account obs_dict
        if self.dirty_flag:
            self.modrev_file = save(self.lqm, self.modrev_file, "lp")
            self.dirty_flag = False
            
        # runs modrev on files
        try:
            # Run modrev with the given model file to check consistency
            result = subprocess.run(
                [self.modrev_path, '-m', self.modrev_file, '-cc', '-v', '0'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if result.returncode != 0:
                # There was an error running modrev
                print(f"Error running modrev: {result}")
                return False

            # checks if output is consistent
            # outpusts modrev answer
            output = json.loads(result.stdout)
            return output.get("consistent", False)

        except Exception as e:
            # Handle the case where modrev output is not valid JSON
            print(f"Error parsing modrev output: {e}")
            return False

    def remove_obs(self, key):
        """
        Removes an observation from the dict by key
        """
        self.obs_dict.pop(key)

    def set_obs(self, observations_dict):
        """
        Sets the observation dict
        """
        self.obs_dict = observations_dict

    def stats(self):
        """
        Shows possible reparation actions in a friendly manner
        """
        # implementation here
        # save (lqm.to_modrev())
        # run modrev on modrev file
        # parse output
        # return possible repairs

    def generate_repairs(self, repair):
        """
        Generates a list of fixed lqm models (as JavaObjects)
        """
        # clones the lqm model
        # applies the repair directly on bioLQM
        # returns all the generated models in the repair process
