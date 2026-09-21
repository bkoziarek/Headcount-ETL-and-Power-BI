#DAX measures

Headcount (EOP) = 
VAR CurrentDate = EOMONTH(MAX(Calendar[Date]),0)
RETURN
CALCULATE(
DISTINCTCOUNT(fact_monthly_snapshot[EmployeeID]),
    fact_monthly_snapshot[MonthEnd] = CurrentDate
)

Headcount (BOP) = 
VAR PreviousMonthEnd =
    EOMONTH(MIN('Calendar'[Date]),-1)
RETURN
CALCULATE(
    DISTINCTCOUNT( fact_monthly_snapshot[EmployeeID] ),
    REMOVEFILTERS(fact_monthly_snapshot[MonthEnd]),
    TREATAS({PreviousMonthEnd},'Calendar'[Date])
)

Avg. Tenure at Exit = AVERAGE(fact_employee_master[TenureAtExitYrs])
Avg. Headcount = DIVIDE([Headcount (EOP)]+[Headcount (BOP)],2)

Promotions = 
CALCULATE (
    DISTINCTCOUNT ( fact_employee_master[EmployeeID] ),
    fact_employee_master[Event] = "Promotion"
)
Involuntary = 
CALCULATE (
    DISTINCTCOUNT ( fact_employee_master[EmployeeID] ),
    fact_employee_master[Event] = "Termination: Involuntary"
)
Net Headcount Change = [New Hires]-[Terminations]
New Hires = 
CALCULATE (
    DISTINCTCOUNT ( fact_employee_master[EmployeeID] ),
    fact_employee_master[Event] = "Hire"
)
Retirement = 
CALCULATE (
    DISTINCTCOUNT ( fact_employee_master[EmployeeID] ),
    fact_employee_master[Event] = "Termination: Retirement"
)
Rolling Turnover 12M = 
VAR EndDate   = MAX ( 'Calendar'[Date] )
VAR StartDate = EDATE ( EndDate, -12 )
VAR Terms =
    CALCULATE ( [Terminations], REMOVEFILTERS ( 'Calendar' ), 'Calendar'[Date] > StartDate, 'Calendar'[Date] <= EndDate )
VAR AvgHC =
    CALCULATE ( [Avg. Headcount], REMOVEFILTERS ( 'Calendar' ), 'Calendar'[Date] > StartDate, 'Calendar'[Date] <= EndDate )
RETURN
DIVIDE ( Terms, AvgHC )
Terminations = 
CALCULATE (
    DISTINCTCOUNT ( fact_employee_master[EmployeeID] ),
    LEFT ( fact_employee_master[Event], 11 ) = "Termination"
)
Turnover = DIVIDE([Terminations]+0,[Avg. Headcount])
Voluntary = 
CALCULATE (
    DISTINCTCOUNT ( fact_employee_master[EmployeeID] ),
    fact_employee_master[Event] = "Termination: Voluntary"
)

Avg. Headcount (YTD) = 
VAR PriorYearEnd = DATE ( YEAR ( MAX ( 'Calendar'[Date] ) ) - 1, 12, 31 )
VAR BOP =
    CALCULATE (
        DISTINCTCOUNT ( fact_monthly_snapshot[EmployeeID] ),
        REMOVEFILTERS ( 'Calendar' ),
        fact_monthly_snapshot[MonthEnd] = PriorYearEnd
    )
RETURN
DIVIDE ( BOP + [Headcount (EOP)], 2 )

New Hires (YTD) = 
TOTALYTD(
    CALCULATE(
        DISTINCTCOUNT(fact_employee_master[EmployeeID]),
        FILTER(
            fact_employee_master,
            fact_employee_master[Event] = "Hire"
            )
    ),
    'Calendar'[Date]
)

Terminations (YTD) = 
TOTALYTD(
    CALCULATE(
        DISTINCTCOUNT(fact_employee_master[EmployeeID]),
        FILTER(
            fact_employee_master,
            LEFT(fact_employee_master[Event],11) = "Termination"
            )
    ),
    'Calendar'[Date]
)

Turnover (YTD) = DIVIDE([Terminations (YTD)]+0,[Avg. Headcount (YTD)])

#CALCULATED COLUMNS

##fact_employee_master

TermReason = IF(LEFT(fact_employee_master[Event],11) = "Termination", MID(fact_employee_master[Event],14,20)
)

TenureAtExitYrs = 
IF (
    LEFT ( fact_employee_master[Event], 11 ) = "Termination",
    DIVIDE (
        DATEDIFF ( RELATED ( dim_employee[HireDate] ), fact_employee_master[EffectiveFrom], DAY ),
        365.25 -- taking fractional years into consideration
    )
)


##fact_monthly_snapshot

HireDate = RELATED(dim_employee[HireDate]) 

Tenure Years = 
DIVIDE(
    DATEDIFF(
        fact_monthly_snapshot[HireDate],
        fact_monthly_snapshot[MonthEnd],
        DAY
    ),
    365.25  -- taking fractional years into consideration
)

Tenure Bucket = 
VAR TenureYrs = [Tenure Years]
RETURN
SWITCH(
    TRUE(),
    TenureYrs < 1, "<1 year",
    TenureYrs < 3, "1–3 years",
    TenureYrs < 5, "3–5 years",
    "5+ years"
)