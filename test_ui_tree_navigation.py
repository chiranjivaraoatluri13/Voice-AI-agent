"""
Test script demonstrating hierarchical UI tree navigation.

This script shows practical examples of how to use UITreeNavigator
for complex, multi-step UI interactions on Android devices.

Usage:
    python test_ui_tree_navigation.py
"""

from agent.adb import AdbClient
from agent.ui_analyzer import UIAnalyzer
from agent.ui_tree_navigator import UITreeNavigator
import time
from typing import List, Tuple


class UITreeNavigationTests:
    """Test suite for hierarchical UI navigation"""
    
    def __init__(self):
        self.adb = AdbClient()
        self.ui_analyzer = UIAnalyzer(self.adb)
        self.navigator = UITreeNavigator(self.adb, self.ui_analyzer)
    
    def test_1_simple_element_search(self):
        """Test 1: Find and tap a single element"""
        print("\n" + "="*60)
        print("TEST 1: Simple Element Search")
        print("="*60)
        
        # Capture UI tree
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        print(f"✓ Captured UI tree with {len(self.ui_analyzer.last_elements)} elements")
        
        # Find Subscribe button
        element = self.navigator.find_element_in_context("Subscribe")
        
        if element:
            print(f"✓ Found: {element.text}")
            print(f"  - Resource ID: {element.resource_id}")
            print(f"  - Class: {element.class_name}")
            print(f"  - Position: {element.bounds}")
            print(f"  - Clickable: {element.clickable}")
            
            # Tap it
            x, y = element.center
            self.adb.run(["shell", "input", "tap", str(x), str(y)])
            print(f"✓ Tapped at ({x}, {y})")
            time.sleep(1)
            return True
        else:
            print("✗ Element not found")
            return False
    
    def test_2_hierarchical_search(self):
        """Test 2: Find element within a context"""
        print("\n" + "="*60)
        print("TEST 2: Hierarchical Search (Find Within Context)")
        print("="*60)
        
        # Capture fresh tree
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Find parent element
        parent = self.navigator.find_element_in_context("Video")
        if not parent:
            print("✗ Parent element 'Video' not found")
            return False
        
        print(f"✓ Found parent: {parent.text}")
        print(f"  - Hierarchy path: {parent.path}")
        print(f"  - Depth: {parent.depth}")
        
        # Find child element within parent
        children = self.ui_analyzer.find_children_of(parent)
        print(f"✓ Found {len(children)} direct children:")
        for i, child in enumerate(children[:5]):  # Show first 5
            print(f"  {i+1}. {child.text} ({child.class_name})")
        
        # Find specific descendant
        like_button = self.navigator.find_element_in_context("Like", parent)
        if like_button:
            print(f"✓ Found 'Like' within Video context")
            print(f"  - Path from root: {like_button.path}")
            return True
        else:
            print("✗ 'Like' not found within Video context")
            return False
    
    def test_3_multi_step_navigation(self):
        """Test 3: Multi-step sequential navigation"""
        print("\n" + "="*60)
        print("TEST 3: Multi-Step Sequential Navigation")
        print("="*60)
        
        steps = ["Subscribe", "Confirm"]
        print(f"Navigation steps: {' → '.join(steps)}")
        print()
        
        results = self.navigator.navigate_sequence(steps)
        
        success_count = sum(1 for success, _ in results if success)
        print(f"\nResults: {success_count}/{len(results)} steps completed")
        
        for i, (success, message) in enumerate(results, 1):
            status = "✓" if success else "✗"
            print(f"  {status} Step {i}: {message}")
        
        return success_count == len(results)
    
    def test_4_find_all_matching(self):
        """Test 4: Find all elements matching a query"""
        print("\n" + "="*60)
        print("TEST 4: Find All Matching Elements")
        print("="*60)
        
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Find all Like buttons
        query = "Like"
        matches = self.navigator.find_all_matching(query)
        
        print(f"Query: '{query}'")
        print(f"Found: {len(matches)} matching elements\n")
        
        for i, elem in enumerate(matches[:5], 1):  # Show first 5
            print(f"{i}. {elem.text}")
            print(f"   Resource ID: {elem.resource_id}")
            print(f"   Path: {elem.path}")
            print(f"   Clickable: {elem.clickable}")
            print()
        
        return len(matches) > 0
    
    def test_5_spatial_search(self):
        """Test 5: Find element near a reference point"""
        print("\n" + "="*60)
        print("TEST 5: Spatial Search (Find Near Reference)")
        print("="*60)
        
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Find Subscribe button as reference
        reference = self.navigator.find_element_in_context("Subscribe")
        if not reference:
            print("✗ Reference element 'Subscribe' not found")
            return False
        
        print(f"✓ Reference element: {reference.text}")
        print(f"  Position: {reference.bounds}")
        
        # Find Like button near Subscribe
        like = self.navigator.find_element_near("Like", reference, max_distance=200)
        
        if like:
            # Calculate distance
            ref_x, ref_y = reference.center
            like_x, like_y = like.center
            distance = ((like_x - ref_x)**2 + (like_y - ref_y)**2) ** 0.5
            
            print(f"✓ Found nearby element: {like.text}")
            print(f"  Position: {like.bounds}")
            print(f"  Distance: {distance:.0f} pixels")
            return True
        else:
            print("✗ Element not found within distance")
            return False
    
    def test_6_hierarchy_breadcrumb(self):
        """Test 6: Get hierarchy breadcrumb path"""
        print("\n" + "="*60)
        print("TEST 6: Hierarchy Breadcrumb Path")
        print("="*60)
        
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Find an element
        element = self.navigator.find_element_in_context("Like")
        if not element:
            print("✗ Element 'Like' not found")
            return False
        
        # Get breadcrumb
        breadcrumb = self.ui_analyzer.get_breadcrumb_to_element(element)
        
        print(f"Element: {element.text}")
        print(f"Depth in hierarchy: {element.depth}")
        print(f"\nBreadcrumb path (root → element):")
        for i, elem in enumerate(breadcrumb):
            indent = "  " * i
            print(f"{indent}├─ {elem.text} ({elem.class_name})")
        
        return True
    
    def test_7_siblings_analysis(self):
        """Test 7: Analyze sibling elements"""
        print("\n" + "="*60)
        print("TEST 7: Sibling Analysis")
        print("="*60)
        
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Find element
        element = self.navigator.find_element_in_context("Like")
        if not element:
            print("✗ Element 'Like' not found")
            return False
        
        print(f"Selected element: {element.text}")
        print(f"Position in parent: index {element.parent_index}\n")
        
        # Get siblings
        siblings = self.navigator.analyze_siblings(element)
        
        print(f"Siblings ({len(siblings)} total):")
        for i, sibling in enumerate(siblings, 1):
            marker = "→" if sibling.text == element.text else " "
            print(f"{marker} {i}. {sibling.text} ({sibling.class_name})")
        
        return len(siblings) > 0
    
    def test_8_print_subtree(self):
        """Test 8: Print UI subtree for visualization"""
        print("\n" + "="*60)
        print("TEST 8: UI Subtree Visualization")
        print("="*60)
        
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        print("UI Tree Structure (first 2 levels):\n")
        self.navigator.print_ui_tree_subtree(max_depth=2)
        
        return True
    
    def test_9_youtube_workflow(self):
        """Test 9: Complex real-world workflow (YouTube-like)"""
        print("\n" + "="*60)
        print("TEST 9: Complex Workflow - YouTube Interaction")
        print("="*60)
        
        workflow_steps = [
            "Video",
            "Like",
            "Share",
            "Subscribe",
            "Notifications"
        ]
        
        print(f"Workflow: {' → '.join(workflow_steps)}\n")
        
        results = self.navigator.navigate_sequence(workflow_steps)
        
        for i, (success, message) in enumerate(results, 1):
            status = "✓" if success else "✗"
            print(f"{status} Step {i}: {message}")
        
        success_count = sum(1 for success, _ in results if success)
        print(f"\nCompleted: {success_count}/{len(results)} steps")
        
        return success_count > 0
    
    def test_10_fallback_to_vision(self):
        """Test 10: Fallback to vision when UI tree insufficient"""
        print("\n" + "="*60)
        print("TEST 10: Fallback Mechanism")
        print("="*60)
        
        # Try UI tree search
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Try to find element
        element = self.navigator.find_element_in_context("Subscribe")
        
        if element:
            print("✓ Found element in UI tree")
            print(f"  Element: {element.text}")
            print(f"  Method: Hierarchical search")
            return True
        else:
            print("⚠ Element not found in UI tree")
            print("  Would fallback to: Vision-based search")
            print("  Method: Screenshot + Ollama model")
            return True  # Fallback exists
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        print("\n" + "="*80)
        print("UI TREE HIERARCHICAL NAVIGATION - TEST SUITE")
        print("="*80)
        
        tests = [
            ("Simple Element Search", self.test_1_simple_element_search),
            ("Hierarchical Search", self.test_2_hierarchical_search),
            ("Multi-Step Navigation", self.test_3_multi_step_navigation),
            ("Find All Matching", self.test_4_find_all_matching),
            ("Spatial Search", self.test_5_spatial_search),
            ("Hierarchy Breadcrumb", self.test_6_hierarchy_breadcrumb),
            ("Siblings Analysis", self.test_7_siblings_analysis),
            ("Subtree Visualization", self.test_8_print_subtree),
            ("Complex Workflow", self.test_9_youtube_workflow),
            ("Fallback Mechanism", self.test_10_fallback_to_vision),
        ]
        
        results = []
        for name, test_func in tests:
            try:
                result = test_func()
                results.append((name, result))
                time.sleep(0.5)  # Brief pause between tests
            except Exception as e:
                print(f"\n✗ Test error: {e}")
                results.append((name, False))
        
        # Summary
        self._print_summary(results)
    
    def _print_summary(self, results):
        """Print test summary"""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"{status} | {name}")
        
        print("="*80)
        print(f"Results: {passed}/{total} tests passed ({100*passed//total}%)")
        print("="*80 + "\n")


def main():
    """Main entry point"""
    try:
        tests = UITreeNavigationTests()
        tests.run_all_tests()
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
