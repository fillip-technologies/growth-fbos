"""
People (HCM & ATS) service permission codes, matching identity catalog naming (`people.<entity>.<action>`).
"""

# Recruitment & ATS
RECRUITMENT_READ = "people.recruitment.read"
RECRUITMENT_MANAGE = "people.recruitment.manage"
# An interviewer: sees the interviews assigned to them and gives feedback on those only.
RECRUITMENT_INTERVIEW = "people.recruitment.interview"

# Core Employee Management
EMPLOYEE_READ = "people.employee.read"
EMPLOYEE_MANAGE = "people.employee.manage"

# Attendance & Shifts
ATTENDANCE_READ = "people.attendance.read"
ATTENDANCE_MANAGE = "people.attendance.manage"

# Leaves & Time Off
LEAVE_APPLY = "people.leave.apply"
LEAVE_APPROVE = "people.leave.approve"

# Compensation, Payroll & Expenses
COMPENSATION_READ = "people.compensation.read"
COMPENSATION_MANAGE = "people.compensation.manage"

# Promotions, demotions and transfers: anyone who manages employees may request one;
# approving needs this separate permission (and never the requester).
ROLE_CHANGE_APPROVE = "people.role_change.approve"
# Setup: who the standing approvers (HR head, finance) are.
ROLE_CHANGE_MANAGE = "people.role_change.manage"

# Separation & Offboarding
SEPARATION_MANAGE = "people.separation.manage"

# Identity's own code for applying a role to a user: needed to decide which jobs bring which roles.
IDENTITY_ROLE_ASSIGNMENT_CREATE = "identity.role_assignment.create"

# The business summary (CEO Command Center): company-wide headcount, leave today and payroll total.
SUMMARY_READ = "people.summary.read"
