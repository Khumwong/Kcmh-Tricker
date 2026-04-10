#!/usr/bin/env python3
"""
KCMH Internet Dependency Checker
Scans only your KCMH project files for potential internet dependencies
"""

import os
import re
import sys
from pathlib import Path

class KCMHInternetChecker:
    """Checks KCMH project files for internet dependencies"""
    
    def __init__(self):
        self.internet_patterns = {
            'network_imports': [
                r'import\s+requests',
                r'import\s+urllib',
                r'import\s+http',
                r'import\s+socket',
                r'from\s+urllib',
                r'from\s+requests',
                r'import\s+wget',
                r'import\s+curl',
            ],
            'network_calls': [
                r'requests\.',
                r'urllib\.',
                r'http\.',
                r'urlopen\(',
                r'get\(',
                r'post\(',
                r'download\(',
                r'fetch\(',
            ],
            'urls_and_ips': [
                r'https?://[^\s\'"]+',
                r'ftp://[^\s\'"]+',
                r'www\.[^\s\'"]+',
                r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',  # IP addresses
            ],
            'hardcoded_paths': [
                r'/home/santa/',  # Original computer paths
                r'/home/[^/\s]+/',     # Other user paths
            ],
            'network_functions': [
                r'connect\(',
                r'bind\(',
                r'listen\(',
                r'socket\(',
                r'gethostname\(',
                r'gethostbyname\(',
            ],
            'suspicious_terms': [
                r'server',
                r'client',
                r'host',
                r'port\s*=',
                r'proxy',
                r'dns',
                r'network',
                r'online',
                r'offline',
                r'internet',
                r'update',
                r'download',
                r'upload',
                r'sync',
            ]
        }
    
    def scan_file(self, file_path):
        """Scan a single file for internet dependencies"""
        results = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.split('\n')
                
                for line_num, line in enumerate(lines, 1):
                    for category, patterns in self.internet_patterns.items():
                        for pattern in patterns:
                            matches = re.finditer(pattern, line, re.IGNORECASE)
                            for match in matches:
                                results.append({
                                    'file': file_path,
                                    'line': line_num,
                                    'content': line.strip(),
                                    'category': category,
                                    'pattern': pattern,
                                    'match': match.group()
                                })
        
        except Exception as e:
            print(f"Could not read {file_path}: {e}")
        
        return results
    
    def scan_kcmh_project(self, project_path):
        """Scan the KCMH project directory"""
        all_results = []
        
        # File types to scan
        extensions = ['.py', '.sh', '.conf', '.ini', '.txt', '.desktop', '.json']
        
        project_path = Path(project_path)
        
        # Get all relevant files
        files_to_scan = []
        for ext in extensions:
            files_to_scan.extend(project_path.rglob(f'*{ext}'))
        
        print(f"Scanning {len(files_to_scan)} files in KCMH project...")
        
        for file_path in files_to_scan:
            if file_path.is_file():
                results = self.scan_file(file_path)
                all_results.extend(results)
        
        return all_results
    
    def analyze_results(self, results):
        """Analyze and categorize the results"""
        
        print("\n" + "="*80)
        print("KCMH INTERNET DEPENDENCY ANALYSIS")
        print("="*80)
        
        if not results:
            print("✅ No obvious internet dependencies found in KCMH files!")
            return
        
        # Group by category
        by_category = {}
        for result in results:
            category = result['category']
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(result)
        
        # Analyze each category
        for category, items in by_category.items():
            print(f"\n🔍 {category.upper().replace('_', ' ')} ({len(items)} matches)")
            print("-" * 60)
            
            # Group by file
            by_file = {}
            for item in items:
                file_path = str(item['file'])
                if file_path not in by_file:
                    by_file[file_path] = []
                by_file[file_path].append(item)
            
            for file_path, file_items in by_file.items():
                rel_path = file_path.replace('/home/santa/Workspace/kcmh-zaber-trigger/', '')
                print(f"\n📁 {rel_path}")
                
                for item in file_items:
                    severity = self.assess_severity(item)
                    print(f"   Line {item['line']:3d}: {severity} {item['content']}")
                    if item['category'] == 'hardcoded_paths':
                        print(f"             ⚠️  HARDCODED PATH - needs to be changed!")
                    elif item['category'] == 'urls_and_ips':
                        print(f"             🌐 NETWORK ADDRESS - potential internet dependency")
    
    def assess_severity(self, item):
        """Assess the severity of each finding"""
        high_severity = ['network_imports', 'network_calls', 'urls_and_ips']
        medium_severity = ['hardcoded_paths', 'network_functions']
        
        if item['category'] in high_severity:
            return "🚨"
        elif item['category'] in medium_severity:
            return "⚠️ "
        else:
            return "💡"
    
    def generate_fixes(self, results):
        """Generate specific fixes for found issues"""
        
        print("\n" + "="*80)
        print("RECOMMENDED FIXES")
        print("="*80)
        
        # Check for specific issues
        hardcoded_paths = [r for r in results if r['category'] == 'hardcoded_paths']
        network_calls = [r for r in results if r['category'] in ['network_imports', 'network_calls', 'urls_and_ips']]
        
        if hardcoded_paths:
            print("\n1. 🔧 HARDCODED PATHS (High Priority)")
            print("   These paths from the original computer need to be changed:")
            
            unique_paths = set()
            for item in hardcoded_paths:
                unique_paths.add(item['match'])
            
            for path in unique_paths:
                print(f"   - Change: {path}")
                print(f"     To:     /home/santa/  (or use relative paths)")
        
        if network_calls:
            print("\n2. 🌐 NETWORK DEPENDENCIES (Critical)")
            print("   These require internet and need offline alternatives:")
            
            for item in network_calls:
                rel_path = str(item['file']).replace('/home/santa/Workspace/kcmh-zaber-trigger/', '')
                print(f"   - {rel_path}:{item['line']} - {item['match']}")
        
        print("\n3. 🛠️  QUICK FIXES TO TRY:")
        print("""
   a) Replace hardcoded paths:
      find /home/santa/Workspace/kcmh-zaber-trigger -name "*.py" -exec sed -i 's|/home/santa|/home/santa|g' {} +
   
   b) Add to your launch script:
      export OFFLINE_MODE=1
      export NO_NETWORK=1
   
   c) Check for config files with network settings:
      grep -r "server\|host\|port" /home/santa/Workspace/kcmh-zaber-trigger/
        """)

def main():
    """Main function"""
    
    kcmh_path = "/home/santa/Workspace/kcmh-zaber-trigger"
    
    if len(sys.argv) > 1:
        kcmh_path = sys.argv[1]
    
    if not os.path.exists(kcmh_path):
        print(f"Error: KCMH project path {kcmh_path} does not exist")
        return 1
    
    print(f"🔍 Checking KCMH project for internet dependencies...")
    print(f"📁 Project path: {kcmh_path}")
    
    checker = KCMHInternetChecker()
    results = checker.scan_kcmh_project(kcmh_path)
    
    checker.analyze_results(results)
    checker.generate_fixes(results)
    
    print(f"\n📊 SUMMARY: Found {len(results)} potential internet-related items")
    print("💡 Focus on hardcoded paths and network calls first!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())