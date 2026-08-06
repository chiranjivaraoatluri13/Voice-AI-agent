# =========================
# FILE: agent/ui_tree_navigator.py
# =========================
"""
Hierarchical UI Tree Navigation System

Provides intelligent navigation through Android UI hierarchies for complex tasks:
- Subscribe button → tap shorts → find three dots → click like
- Find element within context of another element
- Navigate through nested UI containers
"""

from typing import List, Optional, Tuple, Dict
from agent.ui_analyzer import UIElement, UIAnalyzer
from agent.adb import AdbClient


class UIContextBreadcrumb:
    """Tracks the current context/path in UI navigation"""
    
    def __init__(self):
        self.path: List[UIElement] = []
        self.stack: List[List[UIElement]] = []
    
    def push(self, element: UIElement) -> None:
        """Enter a new UI context"""
        self.stack.append(self.path)
        self.path = [element]
    
    def pop(self) -> bool:
        """Go back to previous context"""
        if self.stack:
            self.path = self.stack.pop()
            return True
        return False
    
    def add(self, element: UIElement) -> None:
        """Add element to current path"""
        self.path.append(element)
    
    def get_path_string(self) -> str:
        """Get readable path representation"""
        return " > ".join([
            e.text or e.resource_id.split("/")[-1] or e.class_name.split(".")[-1]
            for e in self.path
        ])


class UITreeNavigator:
    """
    Intelligent navigation through Android UI trees.
    Handles complex multi-step interactions like:
      "Click subscribe, then shorts, then like"
    """
    
    def __init__(self, adb: AdbClient, ui_analyzer: UIAnalyzer):
        self.adb = adb
        self.ui_analyzer = ui_analyzer
        self.context = UIContextBreadcrumb()
    
    # ========================================================
    # HIERARCHICAL ELEMENT FINDING
    # ========================================================
    
    def find_element_in_context(self, query: str, 
                                context_element: Optional[UIElement] = None) -> Optional[UIElement]:
        """
        Find an element within a specific context.
        
        Example:
          context_element = find element with text "Subscribe"
          find_in_context("Shorts", context_element) → finds "Shorts" inside Subscribe menu
        
        Args:
            query: What to find ("Shorts", "Like", "Three dots", etc.)
            context_element: Parent element to search within
        
        Returns:
            First matching element within context, or None
        """
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        if not context_element:
            # Search in entire tree
            candidates = self._search_multi_query(query)
            return candidates[0] if candidates else None
        
        # Find descendants of context
        descendants = self.ui_analyzer.find_descendants_of(context_element)
        
        # Search within descendants
        for desc in descendants:
            if self._query_matches(query, desc):
                return desc
        
        return None
    
    def find_element_near(self, query: str, 
                         reference_element: UIElement,
                         max_distance: int = 200) -> Optional[UIElement]:
        """
        Find element near a reference element.
        Useful for finding "Like" near "Subscribe" button.
        
        Args:
            query: What to find
            reference_element: Element to search near
            max_distance: Maximum pixel distance to search
        
        Returns:
            Nearest matching element, or None
        """
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        ref_x, ref_y = reference_element.center
        ref_bounds = (ref_x - max_distance, ref_y - max_distance,
                     ref_x + max_distance, ref_y + max_distance)
        
        candidates = []
        for elem in self.ui_analyzer.last_elements:
            if not self._query_matches(query, elem):
                continue
            
            # Check if element is within bounds
            elem_left, elem_top, elem_right, elem_bottom = elem.bounds
            if (elem_left < ref_bounds[2] and elem_right > ref_bounds[0] and
                elem_top < ref_bounds[3] and elem_bottom > ref_bounds[1]):
                
                # Calculate distance
                ex, ey = elem.center
                distance = ((ex - ref_x) ** 2 + (ey - ref_y) ** 2) ** 0.5
                candidates.append((distance, elem))
        
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        
        return None
    
    # ========================================================
    # SEQUENTIAL NAVIGATION
    # ========================================================
    
    def navigate_sequence(self, steps: List[str]) -> List[Tuple[bool, str]]:
        """
        Execute a sequence of navigation steps.
        
        Example:
          steps = ["Subscribe button", "Shorts", "Three dots", "Like"]
          results = navigator.navigate_sequence(steps)
        
        Args:
            steps: List of ["element name", "element name", ...]
        
        Returns:
            List of (success: bool, message: str) for each step
        """
        results = []
        
        for i, step in enumerate(steps):
            print(f"\n📍 Step {i+1}/{len(steps)}: {step}")
            
            # Find element
            elem = self.find_element_in_context(step)
            
            if not elem:
                # Try broader search
                candidates = self._search_multi_query(step)
                if not candidates:
                    msg = f"❌ Could not find '{step}'"
                    results.append((False, msg))
                    print(f"   {msg}")
                    continue
                elem = candidates[0]
            
            # Tap element
            if elem.clickable or elem.is_interactable():
                x, y = elem.center
                self.adb.run(["shell", "input", "tap", str(x), str(y)])
                
                # Update context
                self.context.add(elem)
                msg = f"✅ Tapped: {elem.text or elem.class_name}"
                results.append((True, msg))
                print(f"   {msg}")
                
                # Small delay for UI to update
                import time
                time.sleep(0.5)
            else:
                msg = f"⚠️ Element not clickable: {step}"
                results.append((False, msg))
                print(f"   {msg}")
        
        return results
    
    # ========================================================
    # SMART SEARCH
    # ========================================================
    
    def _search_multi_query(self, query: str) -> List[UIElement]:
        """
        Search for element using multiple strategies.
        Returns ranked list of matches.
        """
        query_lower = query.lower()
        results = self.ui_analyzer.search(query_lower)
        return results
    
    def _query_matches(self, query: str, element: UIElement) -> bool:
        """Check if element matches query"""
        query_lower = query.lower()
        
        # Text match
        if element.text and query_lower in element.text.lower():
            return True
        
        # Content description match
        if element.content_desc and query_lower in element.content_desc.lower():
            return True
        
        # Resource ID match
        if element.resource_id and query_lower in element.resource_id.lower():
            return True
        
        return False
    
    # ========================================================
    # UI HIERARCHY ANALYSIS
    # ========================================================
    
    def analyze_siblings(self, element: UIElement) -> List[UIElement]:
        """Find all siblings of an element"""
        if element.parent_index is None or element.parent_index < 0:
            return []
        
        parent_idx = element.parent_index
        siblings = [e for e in self.ui_analyzer.last_elements
                   if e.parent_index == parent_idx and e != element]
        
        return siblings
    
    def get_hierarchy_path(self, element: UIElement) -> str:
        """Get readable hierarchy path to element"""
        path = []
        current_element = element
        elements_copy = self.ui_analyzer.last_elements.copy()
        
        while current_element:
            label = (current_element.text or 
                    current_element.resource_id.split("/")[-1] or 
                    current_element.class_name)
            path.insert(0, label)
            
            if current_element.parent_index is not None and current_element.parent_index >= 0:
                current_element = elements_copy[current_element.parent_index]
            else:
                break
        
        return " > ".join(path)
    
    def print_ui_tree_subtree(self, parent_element: Optional[UIElement] = None, max_depth: int = 5):
        """Print UI tree structure (useful for debugging)"""
        if not parent_element:
            # Find root
            for elem in self.ui_analyzer.last_elements:
                if elem.parent_index is None or elem.parent_index < 0:
                    parent_element = elem
                    break
        
        if not parent_element:
            print("❌ No root element found")
            return
        
        print(f"\n📋 UI Tree Structure (max depth {max_depth}):")
        self._print_tree_node(parent_element, depth=0, max_depth=max_depth)
    
    def _print_tree_node(self, element: UIElement, depth: int, max_depth: int):
        """Helper to recursively print tree nodes"""
        if depth > max_depth:
            return
        
        indent = "  " * depth
        label = element.text or element.content_desc or element.class_name.split(".")[-1]
        clickable = "🔘" if element.clickable else "  "
        
        print(f"{indent}{clickable} {label[:50]}")
        
        children = self.ui_analyzer.find_children_of(element)
        for child in children:
            self._print_tree_node(child, depth + 1, max_depth)
    
    # ========================================================
    # ELEMENT GROUP OPERATIONS
    # ========================================================
    
    def find_all_matching(self, query: str, 
                         context: Optional[UIElement] = None) -> List[UIElement]:
        """Find all elements matching query, optionally within context"""
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        if context:
            elements_to_search = self.ui_analyzer.find_descendants_of(context)
        else:
            elements_to_search = self.ui_analyzer.last_elements
        
        query_lower = query.lower()
        matches = []
        
        for elem in elements_to_search:
            if self._query_matches(query_lower, elem) and (elem.clickable or elem.is_interactable()):
                matches.append(elem)
        
        return matches
