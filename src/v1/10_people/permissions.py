"""
People (HCM & ATS) service permission codes, matching identity catalog naming (`people.<entity>.<action>`).
"""

# Recruitment & ATS
RECRUITMENT_READ = "people.recruitment.read"
RECRUITMENT_MANAGE = "people.recruitment.manage"

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

# Separation & Offboarding
SEPARATION_MANAGE = "people.separation.manage"
