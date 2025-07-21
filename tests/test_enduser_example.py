"""
The end-user example

This is how I imagine interacting with this library as an end-user, and serves
as a reference for how I eventually want to design inner parts.

Good luck, future Paul...

- - - - -
🧩 tellus: Simulation sharing & peer sync — atomic implementation checklist
* [x] Simulation class: initial skeleton
    * [x] Create tellus.Simulation class, constructor with name argument.
    * [x] Add attribute to hold simulation locations (empty data structure).
* [x] Simulation.uid attribute
    * [x] Add public uid attribute to Simulation; allow assignment of a uuid.UUID.
* [x] Simulation: add_location method
    * [x] Implement .add_location(location_dict) method.
    * [x] Accept and store locations keyed by name.
    * [x] Handle duplicates: reject or allow replacement (decide and document).
* [x] Location data validation
    * [x] Enforce keys: name, hostname, type (list of str).
    * [x] Make optional field default to False if not given.
* [x] Simulation.locations mapping
    * [x] Store and expose locations as a mapping by name.
    * [x] Support membership checks: if "uni_server" in ...locations.
* [x] Simulation: to_dict() and from_dict()
    * [x] Implement .to_dict() serialization method (incl. locations, uid).
    * [x] Implement .from_dict() classmethod to instantiate from dict.
* [x] Peer class: skeleton
    * [x] Create tellus.Peer class with handle and experiments attributes.
* [x] Peer.register_at_network_node (stub)
    * [x] Method stub: .register_at_network_node(address) (no-op or log).
* [ ] Peer.get_peers_at (stub)
    * [ ] Method stub: .get_peers_at(address) (returns list of peer handles, stubbed for test).
* [ ] Peer.broadcast_experiments (stub)
    * [ ] Method stub: .broadcast_experiments() (no-op).
* [ ] Peer.recieve_experiment_updates toggle
    * [ ] Add .recieve_experiment_updates attribute; settable boolean.
* [ ] Test network fixture/hooks for experiment sharing
    * [ ] Implement test fixture or hooks to simulate networked experiment propagation.
    * [ ] When a location is added to one peer’s experiment and both peers have .recieve_experiment_updates = True, update all relevant peer copies.
* [ ] Pass the end-user test
    * [ ] Ensure all logic is in place so the supplied test passes as written.
 - - - - -

"""

from tellus import Simulation

from animavox.network import Peer


def test_simulation_sharing_user_adds_new_location(
    sample_simulation_awi_locations_with_laptop,
):
    my_experiment = sample_simulation_awi_locations_with_laptop
    # #########################################################################
    # We have a two peer system. Let's imagine a fixture that creates two
    # peer objects:
    andreas = Peer(handle="little_a")
    bernd = Peer(handle="major_b")

    # Peer is the "local object" that knows about your experiments:
    # [NOTE] Important here is that the Peers use the same experiment, but
    #        create unique objects from the same original dict representation:
    andreas.experiments = [Simulation.from_dict(my_experiment.to_dict())]
    bernd.experiments = [Simulation.from_dict(my_experiment.to_dict())]

    # We set up the peers to register at the network:
    andreas.register_at_network_node("localhost")
    bernd.register_at_network_node("localhost")

    # The peers will listen to others found at the network:
    andreas.get_peers_at("localhost")
    bernd.get_peers_at("localhost")

    # We set up the peers to broadcast:
    andreas.broadcast_experiments()
    bernd.broadcast_experiments()

    # We set up the peers to share based on updates:
    andreas.recieve_experiment_updates = True
    bernd.recieve_experiment_updates = True

    # Andreas adds a location:
    andreas.experiments[0].add_location(
        {
            "name": "uni_server",
            "hostname": "learning.super_uni.edu",
            "optional": True,
            "type": ["disk"],
        }
    )

    # Bernd sees this location:
    assert "uni_server" in bernd.experiments[0].locations
