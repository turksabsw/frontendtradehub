# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Dependency Resolution Module for Mock Data Engine.

This module provides the DependencyResolver class for building and analyzing
dependency graphs between DocTypes based on their Link fields. It is critical
for determining the correct order of mock data generation.

Key Features:
1. **Graph Building**: Constructs a directed graph from DocType Link fields
2. **Topological Sort**: Orders DocTypes for generation (Kahn's algorithm)
3. **Cycle Detection**: Identifies circular dependencies (Tarjan's SCC algorithm)
4. **Two-Pass Strategy**: Provides generation plan for handling cycles

The dependency graph represents "depends on" relationships:
- If DocType A has a Link field to DocType B, then A depends on B
- A must be generated after B (or use two-pass approach for cycles)

Usage:
    resolver = DependencyResolver()

    # Build graph for specific DocTypes
    graph = resolver.build_dependency_graph(["Customer", "Sales Invoice", "Item"])

    # Get generation order
    order = resolver.get_generation_order(["Customer", "Sales Invoice", "Item"])

    # Detect cycles
    cycles = resolver.detect_cycles()

    # Get two-pass generation plan
    plan = resolver.get_generation_plan(["Customer", "Sales Invoice"])
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from mock_data_engine.core.meta_reader import DocTypeMeta, FieldInfo


@dataclass
class DependencyEdge:
    """
    Represents a dependency edge in the graph.

    Attributes:
        source: The DocType that has the dependency
        target: The DocType being depended on
        fieldname: The Link field creating this dependency
        is_required: Whether the Link field is mandatory
        is_circular: Whether this edge is part of a circular dependency
    """
    source: str
    target: str
    fieldname: str
    is_required: bool = False
    is_circular: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source": self.source,
            "target": self.target,
            "fieldname": self.fieldname,
            "is_required": self.is_required,
            "is_circular": self.is_circular,
        }


@dataclass
class DependencyNode:
    """
    Represents a node (DocType) in the dependency graph.

    Attributes:
        doctype: The name of the DocType
        dependencies: Set of DocTypes this node depends on
        dependents: Set of DocTypes that depend on this node
        edges: List of dependency edges (with field details)
        in_cycle: Whether this node is part of a cycle
        cycle_id: The ID of the cycle this node belongs to (if any)
    """
    doctype: str
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    edges: List[DependencyEdge] = field(default_factory=list)
    in_cycle: bool = False
    cycle_id: Optional[int] = None

    @property
    def in_degree(self) -> int:
        """Number of incoming edges (dependencies)."""
        return len(self.dependencies)

    @property
    def out_degree(self) -> int:
        """Number of outgoing edges (dependents)."""
        return len(self.dependents)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "doctype": self.doctype,
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
            "edges": [e.to_dict() for e in self.edges],
            "in_degree": self.in_degree,
            "out_degree": self.out_degree,
            "in_cycle": self.in_cycle,
            "cycle_id": self.cycle_id,
        }


@dataclass
class GenerationPlan:
    """
    A generation plan that handles both normal and circular dependencies.

    The plan divides DocTypes into phases:
    - Phase 1: Independent DocTypes (no dependencies in the set)
    - Phase 2: Dependent DocTypes (can be generated after phase 1)
    - Phase 3: Circular DocTypes (require two-pass approach)

    For circular dependencies, the two-pass approach:
    1. First pass: Insert records with NULL for circular Link fields
    2. Second pass: Update records with resolved Link values

    Attributes:
        independent: DocTypes with no dependencies (generate first)
        dependent: DocTypes that depend on independent ones (generate second)
        circular: DocTypes in cycles (require two-pass)
        generation_order: Complete ordered list for generation
        cycles: List of detected cycles (sets of DocTypes)
        circular_edges: Edges that need two-pass handling
        backfill_required: Fields that need backfilling after first pass
    """
    independent: List[str] = field(default_factory=list)
    dependent: List[str] = field(default_factory=list)
    circular: List[str] = field(default_factory=list)
    generation_order: List[str] = field(default_factory=list)
    cycles: List[FrozenSet[str]] = field(default_factory=list)
    circular_edges: List[DependencyEdge] = field(default_factory=list)
    backfill_required: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def has_cycles(self) -> bool:
        """Check if there are any circular dependencies."""
        return len(self.cycles) > 0

    @property
    def total_doctypes(self) -> int:
        """Total number of DocTypes in the plan."""
        return len(self.generation_order)

    def get_phase(self, doctype: str) -> int:
        """
        Get the generation phase for a DocType.

        Returns:
            1 for independent, 2 for dependent, 3 for circular, 0 if not found
        """
        if doctype in self.independent:
            return 1
        if doctype in self.dependent:
            return 2
        if doctype in self.circular:
            return 3
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "independent": self.independent,
            "dependent": self.dependent,
            "circular": self.circular,
            "generation_order": self.generation_order,
            "cycles": [list(c) for c in self.cycles],
            "circular_edges": [e.to_dict() for e in self.circular_edges],
            "backfill_required": self.backfill_required,
            "has_cycles": self.has_cycles,
            "total_doctypes": self.total_doctypes,
        }


class DependencyResolver:
    """
    Resolves dependencies between DocTypes for mock data generation.

    This class builds and analyzes dependency graphs to determine the
    correct order for generating mock data across multiple DocTypes.

    The resolver uses DocTypeMeta to extract Link field relationships
    and builds a directed graph where edges represent "depends on"
    relationships.

    Attributes:
        doctypes: The set of DocTypes being analyzed
        include_child_tables: Whether to include child table dependencies
        excluded_doctypes: DocTypes to exclude from the graph

    Example:
        >>> resolver = DependencyResolver()
        >>> resolver.add_doctypes(["Customer", "Sales Invoice", "Item"])
        >>> order = resolver.get_generation_order()
        >>> print(order)
        ['Item', 'Customer', 'Sales Invoice']

        >>> plan = resolver.get_generation_plan()
        >>> print(plan.independent)
        ['Item', 'Customer']
        >>> print(plan.dependent)
        ['Sales Invoice']
    """

    def __init__(
        self,
        include_child_tables: bool = False,
        excluded_doctypes: Optional[Set[str]] = None
    ):
        """
        Initialize the DependencyResolver.

        Args:
            include_child_tables: Whether to include child table DocTypes
            excluded_doctypes: Set of DocType names to exclude from analysis
        """
        self._include_child_tables = include_child_tables
        self._excluded_doctypes = excluded_doctypes or set()

        # Graph data structures
        self._nodes: Dict[str, DependencyNode] = {}
        self._doctypes: Set[str] = set()

        # Cache for meta objects
        self._meta_cache: Dict[str, "DocTypeMeta"] = {}

        # Cycle detection results (populated by detect_cycles)
        self._cycles: List[FrozenSet[str]] = []
        self._nodes_in_cycles: Set[str] = set()

    @property
    def doctypes(self) -> Set[str]:
        """Get the set of DocTypes being analyzed."""
        return self._doctypes.copy()

    @property
    def node_count(self) -> int:
        """Get the number of nodes in the graph."""
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        """Get the total number of edges in the graph."""
        return sum(len(node.edges) for node in self._nodes.values())

    def _get_meta(self, doctype: str) -> "DocTypeMeta":
        """
        Get DocTypeMeta for a DocType (with caching).

        Args:
            doctype: The DocType name

        Returns:
            DocTypeMeta instance for the DocType
        """
        if doctype not in self._meta_cache:
            from mock_data_engine.core.meta_reader import DocTypeMeta
            self._meta_cache[doctype] = DocTypeMeta(doctype)
        return self._meta_cache[doctype]

    def _should_include_dependency(self, target_doctype: str) -> bool:
        """
        Check if a dependency target should be included.

        Args:
            target_doctype: The target DocType of a Link field

        Returns:
            True if the dependency should be included in the graph
        """
        # Skip excluded DocTypes
        if target_doctype in self._excluded_doctypes:
            return False

        # Only include if target is in our DocType set
        if target_doctype not in self._doctypes:
            return False

        return True

    def add_doctype(self, doctype: str) -> bool:
        """
        Add a single DocType to the resolver.

        Args:
            doctype: The DocType name to add

        Returns:
            True if the DocType was added, False if already exists or excluded
        """
        if doctype in self._excluded_doctypes:
            return False

        if doctype in self._doctypes:
            return False

        self._doctypes.add(doctype)
        self._nodes[doctype] = DependencyNode(doctype=doctype)
        return True

    def add_doctypes(self, doctypes: List[str]) -> int:
        """
        Add multiple DocTypes to the resolver.

        Args:
            doctypes: List of DocType names to add

        Returns:
            Number of DocTypes successfully added
        """
        count = 0
        for doctype in doctypes:
            if self.add_doctype(doctype):
                count += 1
        return count

    def remove_doctype(self, doctype: str) -> bool:
        """
        Remove a DocType from the resolver.

        Args:
            doctype: The DocType name to remove

        Returns:
            True if removed, False if not found
        """
        if doctype not in self._doctypes:
            return False

        self._doctypes.discard(doctype)
        if doctype in self._nodes:
            del self._nodes[doctype]
        if doctype in self._meta_cache:
            del self._meta_cache[doctype]

        # Remove from other nodes' dependencies/dependents
        for node in self._nodes.values():
            node.dependencies.discard(doctype)
            node.dependents.discard(doctype)
            node.edges = [e for e in node.edges if e.target != doctype]

        return True

    def clear(self) -> None:
        """Clear all DocTypes and reset the resolver."""
        self._doctypes.clear()
        self._nodes.clear()
        self._meta_cache.clear()
        self._cycles.clear()
        self._nodes_in_cycles.clear()

    def build_dependency_graph(
        self,
        doctypes: Optional[List[str]] = None
    ) -> Dict[str, Set[str]]:
        """
        Build the dependency graph from Link fields.

        This is the core method that analyzes DocType schemas and builds
        a directed graph representing dependencies.

        Args:
            doctypes: Optional list of DocTypes to analyze. If None, uses
                     already added DocTypes.

        Returns:
            Dictionary mapping DocType -> set of DocTypes it depends on

        Example:
            >>> resolver = DependencyResolver()
            >>> graph = resolver.build_dependency_graph(["Customer", "Sales Invoice"])
            >>> print(graph["Sales Invoice"])
            {'Customer'}  # Sales Invoice depends on Customer
        """
        # Add doctypes if provided
        if doctypes:
            self.add_doctypes(doctypes)

        # Reset edges (keep nodes)
        for node in self._nodes.values():
            node.dependencies.clear()
            node.dependents.clear()
            node.edges.clear()
            node.in_cycle = False
            node.cycle_id = None

        # Build graph from Link fields
        for doctype in self._doctypes:
            try:
                meta = self._get_meta(doctype)

                # Get all Link fields
                for link_field in meta.get_link_fields():
                    target_doctype = link_field.linked_doctype

                    if not target_doctype:
                        continue

                    if not self._should_include_dependency(target_doctype):
                        continue

                    # Create edge: doctype depends on target_doctype
                    edge = DependencyEdge(
                        source=doctype,
                        target=target_doctype,
                        fieldname=link_field.fieldname,
                        is_required=link_field.is_required,
                    )

                    # Update node data
                    self._nodes[doctype].dependencies.add(target_doctype)
                    self._nodes[doctype].edges.append(edge)

                    # Update reverse edge (dependents)
                    if target_doctype in self._nodes:
                        self._nodes[target_doctype].dependents.add(doctype)

                # Optionally include child table dependencies
                if self._include_child_tables:
                    for table_field in meta.get_table_fields():
                        child_doctype = table_field.child_doctype

                        if not child_doctype:
                            continue

                        # Child tables depend on their parent (implicitly)
                        # But we don't add them as dependencies since they're
                        # created inline with the parent

            except Exception:
                # If we can't get meta for a doctype, skip it
                # This can happen if the DocType doesn't exist
                pass

        # Return simple graph representation
        return {
            doctype: node.dependencies.copy()
            for doctype, node in self._nodes.items()
        }

    def get_dependency_graph(self) -> Dict[str, Set[str]]:
        """
        Get the current dependency graph.

        Returns:
            Dictionary mapping DocType -> set of dependencies
        """
        return {
            doctype: node.dependencies.copy()
            for doctype, node in self._nodes.items()
        }

    def get_node(self, doctype: str) -> Optional[DependencyNode]:
        """
        Get the dependency node for a DocType.

        Args:
            doctype: The DocType name

        Returns:
            DependencyNode if found, None otherwise
        """
        return self._nodes.get(doctype)

    def get_dependencies(self, doctype: str) -> Set[str]:
        """
        Get all DocTypes that a given DocType depends on.

        Args:
            doctype: The DocType to get dependencies for

        Returns:
            Set of DocType names this DocType depends on
        """
        node = self._nodes.get(doctype)
        if node:
            return node.dependencies.copy()
        return set()

    def get_dependents(self, doctype: str) -> Set[str]:
        """
        Get all DocTypes that depend on a given DocType.

        Args:
            doctype: The DocType to get dependents for

        Returns:
            Set of DocType names that depend on this DocType
        """
        node = self._nodes.get(doctype)
        if node:
            return node.dependents.copy()
        return set()

    def get_edges_between(
        self,
        source: str,
        target: str
    ) -> List[DependencyEdge]:
        """
        Get all edges (Link fields) between two DocTypes.

        Args:
            source: The source DocType
            target: The target DocType

        Returns:
            List of DependencyEdge objects
        """
        node = self._nodes.get(source)
        if not node:
            return []

        return [e for e in node.edges if e.target == target]

    def get_all_edges(self) -> List[DependencyEdge]:
        """
        Get all edges in the graph.

        Returns:
            List of all DependencyEdge objects
        """
        edges = []
        for node in self._nodes.values():
            edges.extend(node.edges)
        return edges

    def get_independent_doctypes(self) -> List[str]:
        """
        Get DocTypes with no dependencies (in the analyzed set).

        These DocTypes can be generated first without any prerequisites.

        Returns:
            List of DocType names with no dependencies
        """
        return [
            doctype for doctype, node in self._nodes.items()
            if len(node.dependencies) == 0
        ]

    def get_leaf_doctypes(self) -> List[str]:
        """
        Get DocTypes with no dependents (nothing depends on them).

        These are typically at the "end" of dependency chains.

        Returns:
            List of DocType names with no dependents
        """
        return [
            doctype for doctype, node in self._nodes.items()
            if len(node.dependents) == 0
        ]

    def topological_sort(self) -> List[str]:
        """
        Perform topological sort using Kahn's algorithm.

        Kahn's algorithm works by:
        1. Computing in-degree (number of dependencies) for each node
        2. Starting with nodes that have zero in-degree (no dependencies)
        3. Removing processed nodes and reducing in-degrees of dependents
        4. Repeating until no more nodes can be processed

        Returns DocTypes in an order where dependencies come before
        dependents. If cycles exist, the result will be incomplete
        (only non-cyclic nodes will be included).

        Returns:
            List of DocType names in topological order. Dependencies
            appear before the DocTypes that depend on them.

        Example:
            >>> resolver = DependencyResolver()
            >>> resolver.add_doctypes(["Sales Invoice", "Customer", "Item"])
            >>> resolver.build_dependency_graph()
            >>> order = resolver.topological_sort()
            >>> # Customer and Item come before Sales Invoice
            >>> print(order)
            ['Customer', 'Item', 'Sales Invoice']

        Note:
            If the graph contains cycles, the result will only include
            nodes that are not part of any cycle. Use detect_cycles()
            to identify circular dependencies.
        """
        if not self._nodes:
            return []

        # Step 1: Calculate in-degrees for all nodes
        # In-degree represents how many unresolved dependencies a node has
        in_degree: Dict[str, int] = {}
        for doctype in self._nodes:
            # Count only dependencies that are in our graph
            deps_in_graph = self._nodes[doctype].dependencies & set(self._nodes.keys())
            in_degree[doctype] = len(deps_in_graph)

        # Step 2: Initialize queue with nodes having zero in-degree
        # Use deque for O(1) popleft operations
        # Sort for deterministic output order (alphabetical when in-degrees equal)
        zero_in_degree = sorted([dt for dt in self._nodes if in_degree[dt] == 0])
        queue: deque = deque(zero_in_degree)

        # Step 3: Process nodes using BFS-like approach
        result: List[str] = []

        while queue:
            # Remove node with no remaining dependencies
            node = queue.popleft()
            result.append(node)

            # Get dependents sorted for deterministic order
            dependents = sorted(self._nodes[node].dependents)

            # Reduce in-degree for all dependents
            for dependent in dependents:
                if dependent in in_degree:
                    in_degree[dependent] -= 1
                    # If dependent now has zero in-degree, add to queue
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        # Note: If len(result) < len(self._nodes), there are cycles
        # The missing nodes are part of cycles and cannot be ordered
        return result

    def detect_cycles(self) -> List[FrozenSet[str]]:
        """
        Detect circular dependencies using Tarjan's SCC algorithm.

        Tarjan's algorithm finds all strongly connected components (SCCs)
        in a directed graph. An SCC with more than one node represents
        a cycle in the dependency graph.

        Algorithm Overview:
        1. Perform DFS, assigning each node an index (discovery time)
        2. Track the lowest index reachable from each node (lowlink)
        3. Use a stack to track nodes in the current DFS path
        4. When lowlink[v] == index[v], all nodes on the stack above v
           form a strongly connected component

        Returns:
            List of frozensets, each containing DocTypes in a cycle.
            Single-node SCCs (no cycle) are not included.

        Example:
            >>> resolver = DependencyResolver()
            >>> # A -> B -> C -> A creates a cycle
            >>> resolver.add_doctypes(["A", "B", "C"])
            >>> # Build graph with circular dependencies
            >>> cycles = resolver.detect_cycles()
            >>> # Returns [frozenset({'A', 'B', 'C'})]
        """
        if not self._nodes:
            self._cycles = []
            self._nodes_in_cycles = set()
            return []

        # Tarjan's algorithm state
        index_counter = [0]  # Mutable counter for closure
        index: Dict[str, int] = {}  # Discovery time for each node
        lowlink: Dict[str, int] = {}  # Lowest index reachable
        on_stack: Dict[str, bool] = {}  # Is node on current DFS stack
        stack: List[str] = []  # Current DFS path
        sccs: List[FrozenSet[str]] = []  # Found SCCs

        def strongconnect(v: str) -> None:
            """
            DFS helper function for Tarjan's algorithm.

            Args:
                v: Current node being visited
            """
            # Set the depth index for v to the smallest unused index
            index[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack[v] = True

            # Consider successors of v (nodes that v depends on)
            node = self._nodes.get(v)
            if node:
                for w in sorted(node.dependencies):  # Sorted for determinism
                    if w not in self._nodes:
                        # Skip dependencies not in our graph
                        continue

                    if w not in index:
                        # Successor w has not yet been visited; recurse on it
                        strongconnect(w)
                        lowlink[v] = min(lowlink[v], lowlink[w])
                    elif on_stack.get(w, False):
                        # Successor w is in stack and hence in the current SCC
                        # If w is not on stack, then (v, w) is an edge pointing
                        # to an SCC already found and must be ignored
                        lowlink[v] = min(lowlink[v], index[w])

            # If v is a root node, pop the stack and generate an SCC
            if lowlink[v] == index[v]:
                scc: Set[str] = set()
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    scc.add(w)
                    if w == v:
                        break
                # Only consider SCCs with more than one node as cycles
                if len(scc) > 1:
                    sccs.append(frozenset(scc))

        # Run Tarjan's algorithm from each unvisited node
        # Sort for deterministic iteration order
        for v in sorted(self._nodes.keys()):
            if v not in index:
                strongconnect(v)

        # Store results
        self._cycles = sccs
        self._nodes_in_cycles = set()

        # Mark nodes that are in cycles
        cycle_id = 0
        for cycle in self._cycles:
            for doctype in cycle:
                self._nodes_in_cycles.add(doctype)
                if doctype in self._nodes:
                    self._nodes[doctype].in_cycle = True
                    self._nodes[doctype].cycle_id = cycle_id
            cycle_id += 1

        # Clear cycle flags for nodes not in cycles
        for doctype in self._nodes:
            if doctype not in self._nodes_in_cycles:
                self._nodes[doctype].in_cycle = False
                self._nodes[doctype].cycle_id = None

        return self._cycles.copy()

    def has_cycles(self) -> bool:
        """
        Check if the graph has any cycles.

        Returns:
            True if cycles exist, False otherwise
        """
        if not self._cycles:
            self.detect_cycles()
        return len(self._cycles) > 0

    def get_cycle_for_doctype(self, doctype: str) -> Optional[FrozenSet[str]]:
        """
        Get the cycle containing a specific DocType.

        Args:
            doctype: The DocType to check

        Returns:
            Frozenset of DocTypes in the cycle, or None if not in a cycle
        """
        if not self._cycles:
            self.detect_cycles()

        for cycle in self._cycles:
            if doctype in cycle:
                return cycle
        return None

    def get_generation_order(
        self,
        doctypes: Optional[List[str]] = None
    ) -> List[str]:
        """
        Get the recommended order for generating mock data.

        This combines topological sort with cycle handling to produce
        a complete generation order.

        Args:
            doctypes: Optional list of DocTypes. If None, uses all added DocTypes.

        Returns:
            List of DocType names in recommended generation order
        """
        if doctypes:
            self.build_dependency_graph(doctypes)

        # Get topological sort result
        sorted_doctypes = self.topological_sort()

        # If we got all DocTypes, return as is
        if len(sorted_doctypes) == len(self._nodes):
            return sorted_doctypes

        # Otherwise, detect cycles and append cyclic nodes at the end
        self.detect_cycles()

        # Add cyclic nodes after sorted ones
        cyclic_nodes = [dt for dt in self._nodes if dt not in sorted_doctypes]

        return sorted_doctypes + cyclic_nodes

    def get_generation_plan(
        self,
        doctypes: Optional[List[str]] = None
    ) -> GenerationPlan:
        """
        Get a detailed generation plan for handling all dependencies.

        The plan categorizes DocTypes into three phases:
        1. Independent: No dependencies, generate first
        2. Dependent: Dependencies satisfied by phase 1, generate second
        3. Circular: In dependency cycles, require two-pass approach

        Args:
            doctypes: Optional list of DocTypes. If None, uses all added DocTypes.

        Returns:
            GenerationPlan with detailed generation strategy
        """
        if doctypes:
            self.build_dependency_graph(doctypes)

        plan = GenerationPlan()

        # Detect cycles first
        self.detect_cycles()
        plan.cycles = self._cycles.copy()

        # Get topological order
        sorted_doctypes = self.topological_sort()

        # Categorize DocTypes
        independent_set: Set[str] = set()
        dependent_set: Set[str] = set()

        for doctype in sorted_doctypes:
            node = self._nodes[doctype]

            if len(node.dependencies) == 0:
                # No dependencies - independent
                independent_set.add(doctype)
                plan.independent.append(doctype)
            else:
                # Has dependencies - dependent
                dependent_set.add(doctype)
                plan.dependent.append(doctype)

        # Handle circular dependencies
        for doctype in self._nodes:
            if doctype not in sorted_doctypes:
                plan.circular.append(doctype)

                # Find circular edges (edges to other circular nodes)
                node = self._nodes[doctype]
                for edge in node.edges:
                    if edge.target in self._nodes_in_cycles:
                        edge.is_circular = True
                        plan.circular_edges.append(edge)

                        # Track backfill requirement
                        if doctype not in plan.backfill_required:
                            plan.backfill_required[doctype] = []
                        plan.backfill_required[doctype].append(edge.fieldname)

        # Build complete generation order
        plan.generation_order = (
            plan.independent +
            plan.dependent +
            plan.circular
        )

        return plan

    def get_two_pass_plan(
        self,
        doctypes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get a detailed two-pass generation plan for handling circular dependencies.

        The two-pass approach handles cycles by:
        1. First Pass: Insert records with NULL for circular Link fields
        2. Second Pass: Update those fields with actual references

        This method returns a structured plan that the execution engine
        can use to implement the two-pass strategy.

        Args:
            doctypes: Optional list of DocTypes. If None, uses all added DocTypes.

        Returns:
            Dictionary with two-pass strategy details:
            - requires_two_pass: bool
            - first_pass: List of {doctype, null_fields} for first pass
            - second_pass: List of {doctype, update_fields} for backfill
            - generation_order: Complete order for first pass generation
            - cycles: List of detected cycles

        Example:
            >>> resolver = DependencyResolver()
            >>> resolver.build_dependency_graph(["Employee", "Department"])
            >>> # If Employee.department -> Department and
            >>> # Department.manager -> Employee (circular)
            >>> plan = resolver.get_two_pass_plan()
            >>> if plan["requires_two_pass"]:
            ...     for item in plan["first_pass"]:
            ...         # Generate with NULL for circular fields
            ...         pass
            ...     for item in plan["second_pass"]:
            ...         # Update circular fields with actual values
            ...         pass
        """
        generation_plan = self.get_generation_plan(doctypes)

        result: Dict[str, Any] = {
            "requires_two_pass": generation_plan.has_cycles,
            "first_pass": [],
            "second_pass": [],
            "generation_order": generation_plan.generation_order.copy(),
            "cycles": [list(c) for c in generation_plan.cycles],
        }

        if not generation_plan.has_cycles:
            # No cycles - simple linear generation
            for doctype in generation_plan.generation_order:
                result["first_pass"].append({
                    "doctype": doctype,
                    "null_fields": [],  # No fields need to be NULL
                    "phase": generation_plan.get_phase(doctype),
                })
            return result

        # Build first pass plan
        for doctype in generation_plan.generation_order:
            phase = generation_plan.get_phase(doctype)
            null_fields = generation_plan.backfill_required.get(doctype, [])

            result["first_pass"].append({
                "doctype": doctype,
                "null_fields": null_fields.copy(),
                "phase": phase,
                "is_circular": phase == 3,
            })

        # Build second pass plan (only for circular DocTypes)
        for doctype in generation_plan.circular:
            backfill_fields = generation_plan.backfill_required.get(doctype, [])
            if backfill_fields:
                # Get the target DocTypes for each field
                update_info = []
                node = self._nodes.get(doctype)
                if node:
                    for edge in node.edges:
                        if edge.fieldname in backfill_fields:
                            update_info.append({
                                "fieldname": edge.fieldname,
                                "target_doctype": edge.target,
                                "is_required": edge.is_required,
                            })

                result["second_pass"].append({
                    "doctype": doctype,
                    "update_fields": update_info,
                })

        return result

    def break_cycle(self, cycle: FrozenSet[str]) -> List[DependencyEdge]:
        """
        Find edges to break in order to resolve a cycle.

        This method identifies which edges should be set to NULL in the
        first pass and updated in the second pass. It prefers to break
        optional (non-required) edges over required ones.

        Args:
            cycle: A frozenset of DocTypes forming a cycle

        Returns:
            List of DependencyEdge objects that should be broken
            (set to NULL in first pass, updated in second pass)

        Example:
            >>> resolver = DependencyResolver()
            >>> resolver.build_dependency_graph(["A", "B", "C"])
            >>> cycles = resolver.detect_cycles()
            >>> if cycles:
            ...     edges_to_break = resolver.break_cycle(cycles[0])
            ...     # Use edges_to_break to determine NULL fields
        """
        edges_to_break: List[DependencyEdge] = []
        cycle_list = list(cycle)

        # Find all edges within the cycle
        cycle_edges: List[DependencyEdge] = []
        for doctype in cycle_list:
            node = self._nodes.get(doctype)
            if not node:
                continue

            for edge in node.edges:
                if edge.target in cycle:
                    cycle_edges.append(edge)

        if not cycle_edges:
            return edges_to_break

        # Strategy: Break the minimum number of edges to break the cycle
        # Prefer breaking optional edges over required ones
        # Sort edges: optional first, then by fieldname for determinism
        sorted_edges = sorted(
            cycle_edges,
            key=lambda e: (e.is_required, e.source, e.fieldname)
        )

        # For a simple cycle A -> B -> C -> A, breaking one edge is enough
        # For complex cycles, we may need to break multiple edges
        # Use a greedy approach: break edges until cycle is broken

        # Simple heuristic: break one edge per DocType if possible
        # to minimize required NULLs
        doctypes_handled: Set[str] = set()
        for edge in sorted_edges:
            if edge.source not in doctypes_handled:
                edges_to_break.append(edge)
                doctypes_handled.add(edge.source)

                # Mark edge as circular
                edge.is_circular = True

        return edges_to_break

    def get_transitive_dependencies(self, doctype: str) -> Set[str]:
        """
        Get all transitive dependencies for a DocType.

        This includes not just direct dependencies, but also their
        dependencies, recursively.

        Args:
            doctype: The DocType to analyze

        Returns:
            Set of all DocTypes that this DocType transitively depends on
        """
        visited: Set[str] = set()

        def dfs(dt: str) -> None:
            if dt in visited or dt not in self._nodes:
                return
            visited.add(dt)
            for dep in self._nodes[dt].dependencies:
                dfs(dep)

        # Start DFS from direct dependencies
        node = self._nodes.get(doctype)
        if node:
            for dep in node.dependencies:
                dfs(dep)

        return visited

    def get_transitive_dependents(self, doctype: str) -> Set[str]:
        """
        Get all transitive dependents for a DocType.

        This includes not just direct dependents, but also their
        dependents, recursively.

        Args:
            doctype: The DocType to analyze

        Returns:
            Set of all DocTypes that transitively depend on this DocType
        """
        visited: Set[str] = set()

        def dfs(dt: str) -> None:
            if dt in visited or dt not in self._nodes:
                return
            visited.add(dt)
            for dep in self._nodes[dt].dependents:
                dfs(dep)

        # Start DFS from direct dependents
        node = self._nodes.get(doctype)
        if node:
            for dep in node.dependents:
                dfs(dep)

        return visited

    def is_dependency_of(self, doctype: str, potential_dependent: str) -> bool:
        """
        Check if a DocType is a dependency of another.

        Args:
            doctype: The potential dependency
            potential_dependent: The DocType to check

        Returns:
            True if doctype is a (transitive) dependency of potential_dependent
        """
        deps = self.get_transitive_dependencies(potential_dependent)
        return doctype in deps

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the resolver state to a dictionary.

        Useful for serialization, debugging, or visualization.

        Returns:
            Dictionary representation of the resolver
        """
        return {
            "doctypes": list(self._doctypes),
            "nodes": {dt: node.to_dict() for dt, node in self._nodes.items()},
            "cycles": [list(c) for c in self._cycles],
            "statistics": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "has_cycles": self.has_cycles(),
                "cycle_count": len(self._cycles),
            }
        }

    def __repr__(self) -> str:
        """String representation of DependencyResolver."""
        return (
            f"DependencyResolver("
            f"nodes={self.node_count}, "
            f"edges={self.edge_count}, "
            f"cycles={len(self._cycles)}"
            f")"
        )

    def __len__(self) -> int:
        """Return the number of DocTypes in the resolver."""
        return len(self._nodes)

    def __contains__(self, doctype: str) -> bool:
        """Check if a DocType is in the resolver."""
        return doctype in self._doctypes


def build_dependency_graph(doctypes: List[str]) -> Dict[str, Set[str]]:
    """
    Build a dependency graph for a list of DocTypes.

    This is a convenience function that creates a DependencyResolver
    and builds the graph in one step.

    Args:
        doctypes: List of DocType names to analyze

    Returns:
        Dictionary mapping DocType -> set of DocTypes it depends on

    Example:
        >>> graph = build_dependency_graph(["Customer", "Sales Invoice"])
        >>> print(graph["Sales Invoice"])
        {'Customer'}
    """
    resolver = DependencyResolver()
    return resolver.build_dependency_graph(doctypes)


def get_generation_order(
    doctypes: List[str],
    excluded_doctypes: Optional[Set[str]] = None
) -> List[str]:
    """
    Get the recommended generation order for a list of DocTypes.

    This is a convenience function that handles the complete
    dependency resolution process.

    Args:
        doctypes: List of DocType names to order
        excluded_doctypes: Optional set of DocTypes to exclude

    Returns:
        List of DocType names in recommended generation order

    Example:
        >>> order = get_generation_order(["Sales Invoice", "Customer", "Item"])
        >>> print(order)
        ['Customer', 'Item', 'Sales Invoice']
    """
    resolver = DependencyResolver(excluded_doctypes=excluded_doctypes)
    return resolver.get_generation_order(doctypes)


def create_dependency_resolver(
    doctypes: Optional[List[str]] = None,
    include_child_tables: bool = False,
    excluded_doctypes: Optional[Set[str]] = None
) -> DependencyResolver:
    """
    Factory function to create a configured DependencyResolver.

    Args:
        doctypes: Optional initial list of DocTypes to add
        include_child_tables: Whether to include child table dependencies
        excluded_doctypes: Set of DocTypes to exclude

    Returns:
        A configured DependencyResolver instance

    Example:
        >>> resolver = create_dependency_resolver(
        ...     doctypes=["Customer", "Sales Invoice"],
        ...     excluded_doctypes={"User", "Role"}
        ... )
        >>> plan = resolver.get_generation_plan()
    """
    resolver = DependencyResolver(
        include_child_tables=include_child_tables,
        excluded_doctypes=excluded_doctypes,
    )

    if doctypes:
        resolver.add_doctypes(doctypes)
        resolver.build_dependency_graph()

    return resolver
