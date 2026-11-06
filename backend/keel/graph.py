"""The escape graph: spaces as nodes, doors as edges."""
from __future__ import annotations

import networkx as nx

from keel.model import Category, Deck

# A stair enclosure or the open deck ends an escape route on this drawing.
EXIT_CATEGORIES = (Category.STAIR, Category.OPEN_DECK)


def build_graph(deck: Deck, include_door=None) -> nx.Graph:
    graph = nx.Graph()
    for space in deck.spaces:
        graph.add_node(space.id, category=space.category)
    for door in deck.doors:
        if door.space_a and door.space_b and door.space_a != door.space_b:
            if include_door is None or include_door(door):
                graph.add_edge(door.space_a, door.space_b, door=door.id)
    return graph


def exit_ids(deck: Deck) -> set[str]:
    return {s.id for s in deck.spaces if s.category in EXIT_CATEGORIES}


def escape_path(graph: nx.Graph, start: str, exits: set[str]) -> list[str] | None:
    """Shortest door-by-door route to the nearest exit, or None if there is none."""
    best: list[str] | None = None
    for exit_id in exits:
        if exit_id == start or exit_id not in graph or start not in graph:
            continue
        try:
            path = nx.shortest_path(graph, start, exit_id)
        except nx.NetworkXNoPath:
            continue
        if best is None or len(path) < len(best):
            best = path
    return best


def independent_exit_routes(graph: nx.Graph, start: str, exits: set[str]) -> list[str]:
    """Exits reachable from start without leaving through another exit.

    Exits are terminal, so a route through one exit to reach another is not a second route.
    Two door-connected exits still count as two, because each is reached by its own door.
    """
    if start not in graph:
        return []
    reached = []
    for exit_id in sorted(exits):
        if exit_id not in graph:
            continue
        blocked = exits - {exit_id}
        allowed = [n for n in graph.nodes if n not in blocked]
        if nx.has_path(graph.subgraph(allowed), start, exit_id):
            reached.append(exit_id)
    return reached
