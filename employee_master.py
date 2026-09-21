import logging

import pandas as pd, numpy as np

from pathlib import Path



BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "output"
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


# logging setup
logging.basicConfig(
    filename=LOG_DIR / "data_quality_log.txt",
    filemode="a",              # append, so each run adds to history instead of overwriting
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.info("=== Pipeline run started ===")



def read_csv_file(filename: str) -> pd.DataFrame:
    """Read a CSV from the project's data folder with robust error handling."""
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Expected file not found: {path}")

    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        # Try fallback encodings automatically
        for enc in ("utf-8", "latin1", "cp1250"):
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"{path} has encoding issues — tried utf-8, latin1, cp1250")
    except pd.errors.EmptyDataError:
        raise ValueError(f"{path} is empty or not valid CSV")
    except pd.errors.ParserError:
        raise ValueError(f"{path} could not be parsed as CSV")
    except Exception as e:
        logging.exception(f"Unexpected error while reading CSV: {e}")
        raise




if __name__ == "__main__":

    # reading csv files

    df_hires = read_csv_file("fact_hires.csv")
    df_term = read_csv_file("fact_terminations.csv")
    df_sc = read_csv_file("fact_statuschanges.csv")
    df_dimemployee = read_csv_file("dim_employee.csv")



    # checking for zero duration employees and events logged after termination, excluding those records to log file

    zero_duration = df_term.merge(df_hires[["EmployeeID", "HireDate"]], on="EmployeeID")
    zero_duration = zero_duration[zero_duration["HireDate"] == zero_duration["TerminationDate"]]

    # if hire = termination, employee is logged as zero duration employee
    if len(zero_duration) > 0:
        logging.warning(f"Excluded {len(zero_duration)} employee(s) hired and terminated same day.")
        zero_duration.to_csv(LOG_DIR / "excluded_zero_duration_employees.csv", index=False)
        df_hires = df_hires[~df_hires["EmployeeID"].isin(zero_duration["EmployeeID"])]
        df_term = df_term[~df_term["EmployeeID"].isin(zero_duration["EmployeeID"])]
    else:
        logging.info("No zero-duration (same-day hire+termination) employees found.")

    # checking for events logged after termination date
    df_sc = df_sc.merge(df_dimemployee[["EmployeeID", "TerminationDate"]], on="EmployeeID", how="left")
    after_term_event = df_sc["TerminationDate"].notna() & (df_sc["EventDate"] > df_sc["TerminationDate"])
    dropped_events = df_sc[after_term_event]

    if len(dropped_events) > 0:
        logging.warning(f"Dropped {len(dropped_events)} status-change event(s) logged after termination.")
        dropped_events.to_csv(LOG_DIR / "excluded_post_termination_events.csv", index=False)
    else:
        logging.info("No status-change events found after termination.")

    df_sc = df_sc[~after_term_event].drop(columns=["TerminationDate"])




    # creating employee master dataframme and populating with data from fact_hire and dim_employee
    # employee master headers: EmployeeID	DepartmentID	JobLevelID	EffectiveFrom	EffectiveTo	Event Gender
    # mapping HireDate --> EffectiveFrom, DepartmentID --> DepartmentID

    df_emp_master = pd.DataFrame(columns = ["EmployeeID","DepartmentID","JobLevelID","EffectiveFrom","EffectiveTo", "Event"])
    df_emp_master["EmployeeID"] = df_hires["EmployeeID"]
    #merging hire data from fact hires
    df_emp_master = df_emp_master.merge(df_hires, how = "left",on="EmployeeID")
    #merging job level and gender from dim_employees
    df_emp_master = df_emp_master.merge(df_dimemployee[["EmployeeID","Gender","JobLevelID"]], how = "left", on="EmployeeID")
    #removing redundant columns created with merge
    df_emp_master = df_emp_master.rename(columns={"DepartmentID_y":"DepartmentID","JobLevelID_y":"JobLevelID"})
    df_emp_master["EffectiveFrom"] = df_emp_master["HireDate"]
    df_emp_master = df_emp_master.drop(columns = ["HireDate","DepartmentID_x","JobLevelID_x"])
    df_emp_master["Event"] = "Hire"

    #populating data from fact status change table to employee master. Filtering for each status change and concatenating tables

    #creating copies of dataframe, filtered by event type
    df_dept = df_sc[df_sc["EventType"]=="DepartmentChange"].copy()
    df_prom = df_sc[df_sc["EventType"]=="Promotion"].copy()
    df_jlc = df_sc[df_sc["EventType"]=="JobLevelChange"].copy()

    #combining 2 event types that share the same value change (job code)
    df_combined = pd.concat([df_prom,df_jlc],ignore_index = True)

    ###### checking for edge cases, logging to file if any found
    
    # promotions not changing job level
    df_prom["OldValue"] = df_prom.groupby("EmployeeID")["NewValue"].shift(1)
    same_level_promotions = df_prom[df_prom["NewValue"] == df_prom["OldValue"]]

    if len(same_level_promotions) > 0:
        logging.warning(f"{len(same_level_promotions)} promotions did not change job level.")
        same_level_promotions.to_csv(LOG_DIR / "dq_same_level_promotions.csv", index=False)

    # dept changes not changing department code
    df_dept["OldValue"] = df_dept.groupby("EmployeeID")["NewValue"].shift(1)
    same_dept_changes = df_dept[df_dept["NewValue"] == df_dept["OldValue"]]

    if len(same_dept_changes) > 0:
        logging.warning(f"{len(same_dept_changes)} department changes did not change department.")
        same_dept_changes.to_csv(LOG_DIR / "dq_same_department_changes.csv", index=False)

    # identifying potential demotions
    df_jlc["OldValue"] = df_jlc.groupby("EmployeeID")["NewValue"].shift(1)
    demotions = df_jlc[df_jlc["NewValue"] < df_jlc["OldValue"]]

    if len(demotions) > 0:
        logging.warning(f"{len(demotions)} job level decreases detected (possible demotions).")
        demotions.to_csv(LOG_DIR / "dq_demotions.csv", index=False)







    #mapped column names, for concatenation
    mapping_dept = {"EventDate":"EffectiveFrom","EventType":"Event","NewValue":"DepartmentID"}
    mapping_prom_jlc = {"EventDate":"EffectiveFrom","EventType":"Event","NewValue":"JobLevelID"}
    mapping_term = {"TerminationDate":"EffectiveFrom","TerminationReason":"Event"}


    #preparing columns and dataframes for concatenation
    df_dept = df_dept.rename(columns = mapping_dept)
    df_dept["JobLevelID"] = None
    df_dept["EffectiveTo"] = None

    df_combined = df_combined.rename(columns = mapping_prom_jlc)
    df_combined["DepartmentID"] = None
    df_combined["EffectiveTo"] = None


    df_term_concat = df_term.rename(columns = mapping_term)
    df_term_concat["Event"] = "Termination: " + df_term_concat["Event"]
    df_term_concat["JobLevelID"] = None
    df_term_concat["EffectiveTo"] = None

    df_concat1 = df_dept[
        ['EmployeeID',
        'DepartmentID',
        'JobLevelID',
        'EffectiveFrom',
        'EffectiveTo',
        'Event']
        ]

    df_concat2 = df_combined[
        ['EmployeeID',
        'DepartmentID',
        'JobLevelID',
        'EffectiveFrom',
        'EffectiveTo',
        'Event']
        ]

    df_concat3 = df_term_concat

    #concatenating columns and outputting employee master dataframe with added department change, job change, effective from and event name
    df_emp_master = pd.concat([df_emp_master,df_concat1,df_concat2, df_concat3],ignore_index = True)

    #resetting index
    df_emp_master = df_emp_master.reset_index(drop = True)

  
    #deriving effective to date based on next effective from = 1 day
    # change column type to datetime before sorting
    df_emp_master["EffectiveFrom"] = pd.to_datetime(df_emp_master["EffectiveFrom"])


    # adding weights for events in case of multiple events on same day
    priority_map = {
        "Termination: Retirement": 100,
        "Termination: Involuntary": 90,
        "Termination: Voluntary": 80,
        "Promotion": 70,
        "JobLevelChange": 60,
        "DepartmentChange": 50,
        "Hire": 10,
        None: 0
    }

    df_emp_master["EventPriority"] = df_emp_master["Event"].map(priority_map)

    #sort by employee id date and priority before picking
    df_emp_master = df_emp_master.sort_values(
        ["EmployeeID", "EffectiveFrom", "EventPriority"],
        ascending=[True, True, False]
    )
    # dropping event priority column after sorting, as it is no longer needed 
    df_emp_master = df_emp_master.drop(columns=["EventPriority"])

    # deriving effective to date based on next effective from - 1 day
    df_emp_master["EffectiveTo"] = (
        df_emp_master.groupby("EmployeeID")["EffectiveFrom"].shift(-1) - pd.Timedelta(days=1)
    )


    #applying forward fill to Gender, dept id and job level (filling data per employee, based on earlier record)

    df_emp_master[["Gender", "DepartmentID", "JobLevelID"]] = (
        df_emp_master.groupby("EmployeeID")[["Gender", "DepartmentID", "JobLevelID"]].ffill()
    )


    # cross check emp_master vs terminations - adding active/inactive flag

    #setting emp id as index for .map
    term_dates = df_dimemployee.set_index("EmployeeID")["TerminationDate"]
    term_dates = pd.to_datetime(term_dates)


    terminated_condition = df_emp_master['EmployeeID'].map(term_dates).notna() &(df_emp_master['EffectiveFrom'] == df_emp_master['EmployeeID'].map(term_dates))

    df_emp_master['Status'] = np.where(
        terminated_condition,
        'Inactive', 'Active'
    )

    df_emp_master['EffectiveTo'] = np.where(
        terminated_condition,
        df_emp_master['EmployeeID'].map(term_dates),   # termination date
        df_emp_master['EffectiveTo']                   # keep existing value
    )

    #filling remaining effective to with either effective to = termination date, or end-of-time date if employee still active
    df_emp_master["EffectiveTo"] = df_emp_master["EffectiveTo"].fillna(pd.Timestamp("9999-12-31"))

    # loggingevents logged before hire date
    hire_dates = df_hires.set_index("EmployeeID")["HireDate"]
    df_emp_master["HireDate"] = df_emp_master["EmployeeID"].map(hire_dates)

    events_before_hire = df_emp_master[df_emp_master["EffectiveFrom"] < df_emp_master["HireDate"]]

    if len(events_before_hire) > 0:
        logging.warning(f"{len(events_before_hire)} events occurred before hire date.")
        events_before_hire.to_csv(LOG_DIR / "dq_events_before_hire.csv", index=False)

    df_emp_master = df_emp_master[df_emp_master["EffectiveFrom"] >= df_emp_master["HireDate"]]
    df_emp_master = df_emp_master.drop(columns=["HireDate"])

    # checking for effective from > effective to, logging to file if any found
    invalid_ranges = df_emp_master[df_emp_master["EffectiveFrom"] > df_emp_master["EffectiveTo"]]

    if len(invalid_ranges) > 0:
        logging.warning(f"{len(invalid_ranges)} records have EffectiveFrom > EffectiveTo.")
        invalid_ranges.to_csv(LOG_DIR / "dq_invalid_effective_ranges.csv", index=False)

    #checking for rehires
    rehire_events = df_hires[df_hires.duplicated("EmployeeID", keep=False)]

    if len(rehire_events) > 0:
        logging.warning(f"{len(rehire_events)} rehire events detected.")
        rehire_events.to_csv(LOG_DIR / "dq_rehires.csv", index=False)

    # writing to csv file
    df_emp_master.to_csv(OUTPUT_DIR / "employee_master.csv", index=False)





    # snapshot_start = df_employee_master["EffectiveFrom"].min()
    snapshot_end = pd.Timestamp("2025-12-31")

    #masking 9999-12-31 dates with snapshot_end (2025-12-31)
    df_emp_master["EffectiveTo"] = df_emp_master["EffectiveTo"].mask(df_emp_master["EffectiveTo"] > snapshot_end, snapshot_end)

    #creating dataframe with month end dates for all months in range
    months = pd.date_range("2019-01-31", snapshot_end, freq="ME")
    df_months = pd.DataFrame({"MonthEnd": months})

    #creating dataframe with unique employees and cross merging with month dataframe
    df_employees = df_emp_master[["EmployeeID"]].drop_duplicates()
    df_months = df_employees.merge(df_months, how="cross")

    # merging with employee master
    df_join = df_months.merge(df_emp_master, on="EmployeeID", how="left")

    # filtering for events based on snapshot months
    df_active = df_join[
        (df_join["MonthEnd"] >= df_join["EffectiveFrom"]) &
        (df_join["MonthEnd"] <= df_join["EffectiveTo"]) &
        (df_join["Status"] == "Active")
    ]

    # keeping last record in month for every employee - ensuring that most recent data is displayed for every month end
    df_snapshot = (
        df_active
        .sort_values(["EmployeeID", "MonthEnd", "EffectiveFrom"], ascending=[True, True, False])
        .groupby(["EmployeeID", "MonthEnd"], as_index=False)
        .first()
    )

    # picking columns for output file and outputting to csv
    df_snapshot = df_snapshot[[
    'EmployeeID',
    'DepartmentID',
    'Gender',
    'JobLevelID',
    "MonthEnd"
    ]].sort_values(["MonthEnd", "EmployeeID"])


    df_snapshot.to_csv(OUTPUT_DIR / "monthly_snapshot.csv", index=False)
