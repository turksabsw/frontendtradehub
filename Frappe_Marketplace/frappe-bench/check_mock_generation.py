#!/usr/bin/env python3
"""
Script to check mock generation status from terminal.
Usage: bench --site marketplace.local execute check_mock_generation.check_status
"""

import frappe

def check_status(request_name=None):
    """Check status of mock generation requests."""
    frappe.init(site='marketplace.local')
    frappe.connect()
    
    if request_name:
        # Check specific request
        try:
            request = frappe.get_doc("Mock Generation Request", request_name)
            print(f"\n=== Mock Generation Request: {request_name} ===")
            print(f"Status: {request.status}")
            print(f"Progress: {request.progress_percent}%")
            print(f"Records Created: {request.records_created}")
            print(f"Records Failed: {request.records_failed}")
            print(f"Current Batch: {request.current_batch}/{request.total_batches}")
            print(f"Started At: {request.started_at}")
            print(f"Queued At: {request.queued_at}")
            if request.error_message:
                print(f"Error: {request.error_message}")
        except frappe.DoesNotExistError:
            print(f"Request {request_name} not found!")
    else:
        # List all recent requests
        requests = frappe.get_all(
            "Mock Generation Request",
            fields=["name", "status", "progress_percent", "records_created", "records_failed", "queued_at", "started_at"],
            order_by="creation desc",
            limit=10
        )
        
        print("\n=== Recent Mock Generation Requests ===")
        for req in requests:
            print(f"\n{req.name}:")
            print(f"  Status: {req.status}")
            print(f"  Progress: {req.progress_percent}%")
            print(f"  Created: {req.records_created}, Failed: {req.records_failed}")
            print(f"  Queued: {req.queued_at}")
            if req.started_at:
                print(f"  Started: {req.started_at}")

def check_background_jobs():
    """Check if background jobs are running."""
    frappe.init(site='marketplace.local')
    frappe.connect()
    
    from frappe.utils.background_jobs import get_jobs
    
    print("\n=== Background Jobs ===")
    try:
        jobs = get_jobs()
        mock_jobs = [j for j in jobs if 'mock_gen' in str(j.get('job_id', ''))]
        
        if mock_jobs:
            print(f"Found {len(mock_jobs)} mock generation jobs:")
            for job in mock_jobs:
                print(f"  Job ID: {job.get('job_id')}")
                print(f"  Status: {job.get('status')}")
                print(f"  Function: {job.get('method')}")
        else:
            print("No mock generation jobs found in queue.")
    except Exception as e:
        print(f"Error checking jobs: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        check_status(sys.argv[1])
    else:
        check_status()
        check_background_jobs()







