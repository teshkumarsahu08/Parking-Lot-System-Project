# GoParking — Smart Parking Management System

A smart parking management system built using Java, Python, Streamlit, and SQLite to simplify vehicle parking, slot allocation, vehicle searching, parking history, and fee management. This project demonstrates the practical application of Data Structures and Algorithms (DSA) in a real-world parking management scenario.

Overview

Traditional parking management often relies on manual registers, making it difficult to track available parking slots, locate vehicles, maintain entry and exit records, and calculate parking fees.

GoParking addresses these problems through a web-based interface connected to a Java parking engine and an SQLite database. It uses efficient data structures to manage parking slots and active vehicles.

# Features

- User Authentication: Account registration and sign-in.
- Vehicle Registration: Register vehicles with registration numbers, colors, and vehicle types.
- Smart Slot Allocation: Automatically assigns the lowest-numbered available parking slot.
- Duplicate Prevention: Prevents a vehicle from being parked more than once at a time.
- Live Parking Status: Displays total, occupied, and available parking slots.
- Vehicle Search: Search for vehicles by registration number and color.
- Vehicle Exit: Remove parked vehicles and release their slots.
- Parking History: Maintain records of parking visits.
- Fee Management: Estimate parking fees based on parking duration and record payments.
- Admin Controls: Manage users, hourly parking rates, and system-wide information.
- CSV Export: Support data export using pandas.

# Technology Stack

Component| Technology
Frontend / Web Interface| Python, Streamlit
Parking Management Engine| Java
Database| SQLite
Data Processing and Export| pandas
Password Security| hashlib, hmac, secrets
Python–Java Communication| TCP Socket
Testing| Python unittest, Java smoke test

# System Architecture

GoParking uses a three-part architecture:

1. Streamlit Application (Python): Provides the user interface, handles authentication, manages database operations, and displays parking information.
2. Java Parking Engine: Handles parking logic, slot allocation, vehicle lookup, and vehicle removal.
3. SQLite Database: Stores persistent application data, including user and vehicle records, parking events, history, and payment records.

The Python application communicates with the Java parking server using a line-based text protocol over a TCP socket. The Java server is configured for port "5000".

                 User / Browser
                       |
                       v
              Python + Streamlit
                   (app.py)
                       |
             +---------+---------+
             |                   |
             v                   v
        TCP Socket           SQLite Database
       Port 5000             goparking.db
             |
             v
       Java ParkingServer
             |
             v
          ParkingLot
             |
     +-------+-------+
     |       |       |
  TreeSet HashMap ArrayList

Data Structures and Algorithms Used

The main focus of this project is applying the right data structure to each parking operation.

Data Structure| Application| Purpose
"TreeSet<Integer>"| Available parking slots| Retrieves the lowest-numbered free slot efficiently
"HashMap<String, ParkingSlot>"| Active vehicle lookup| Finds active vehicles and checks duplicate registrations
"ArrayList<Vehicle>"| Active vehicles| Stores and iterates through vehicle records
"ArrayList<ParkingHistory>"| Parking history| Appends and maintains visit records
"HashSet<String>"| Vehicle types| Checks whether a vehicle type is allowed
Linear Search| Color and history searches| Finds matching records by scanning entries

Why TreeSet and HashMap?

TreeSet: Maintains available slot numbers in sorted order. Calling "first()" returns the smallest available slot, allowing GoParking to allocate the lowest-numbered free slot.

HashMap: Maps a normalized vehicle registration number to its active parking slot. It supports expected (O(1)) lookup and duplicate checking.

Example:

Available slots: {1, 3, 5}

Vehicle enters:
Assigned slot: 1

Available slots: {3, 5}

Vehicle exits:
Available slots: {1, 3, 5}

This approach demonstrates how choosing suitable data structures can improve the efficiency of a real-world application.

Application Workflow

1. Vehicle Entry

1. The user submits the vehicle registration number, color, and type.
2. Python saves the vehicle information in SQLite.
3. The Java engine validates the request and checks for duplicates and available capacity.
4. The lowest-numbered free slot is assigned.
5. Parking records are updated and the assigned slot is displayed.

2. Vehicle Exit

1. The user selects a parked vehicle.
2. The application verifies vehicle ownership.
3. The Java engine releases the parking slot.
4. Python calculates the parking fee based on the parking duration.
5. Parking history and payment records are updated.

3. Vehicle Search

Users can search by registration number or vehicle color to find relevant vehicle records.

Time and Space Complexity

Let:

- (s) = number of parking slots
- (n) = number of active vehicles
- (h) = number of history records

Operation| Time Complexity
Initialize available slots| (O(s \log s))
Allocate the lowest free slot| (O(\log s))
Registration lookup / duplicate check| Expected (O(1))
Search by color| (O(n))
Remove vehicle and update records| (O(n+h))
Build slot-status response| (O(sn))
Append a vehicle or history record| Amortized (O(1))

Java engine space complexity: (O(s+n+h)).

These complexities describe the operations documented in the current implementation. Actual performance depends on the number of slots, vehicles, and history records.

Requirements

Before running the project, ensure you have:

- Python 3 installed.
- Java Development Kit (JDK) installed.
- pip for installing Python packages.
- Streamlit and pandas installed.
- The project source files and required dependencies.

Install the main Python packages with:

pip install streamlit pandas

Install any additional dependencies required by the project if applicable.

Running the Project

The repository should contain the Streamlit application ("app.py"), the Python authentication module ("auth_security.py"), and the Java parking engine source files.

Step 1: Start the Java parking server

Compile the Java source files according to their package structure, then run the class containing the "main()" method for "ParkingServer". Ensure the server is available on the expected port, "5000".

Step 2: Start the Streamlit application

From the project directory, run:

streamlit run app.py

Step 3: Open the application

Open the local URL printed by Streamlit in your browser, register or sign in, and explore the parking management features.

«Note: Start the Java server before using features that require the parking engine. The exact Java compilation command depends on the source-file and package structure in your repository.»

Testing

The following checks are documented in the project presentation:

- Python unit tests: 4 tests passed for password and email helper functions.
- Java smoke test: Passed for allocation, duplicate prevention, full-lot handling, invalid vehicle types, removal, lookup, and restore.
- Python syntax checks: Passed for "app.py" and "auth_security.py".
- Full integration testing: Not yet completed.
- Performance benchmarking: Not yet completed.

Current Limitations

- Java parking occupancy is maintained in memory; restoration is best-effort.
- Java state and SQLite updates are not part of a single transaction.
- The TCP protocol does not provide authentication, and explicit loopback-only binding is not guaranteed.
- Color search and slot-layout generation involve linear scans.
- The system does not currently support reservations, parking sensors, or real payment processing.
- Full end-to-end integration testing and performance benchmarking remain pending.

Future Enhancements

- Improve consistency between the Java engine and SQLite database.
- Secure the parking server through authentication and appropriate network binding.
- Add comprehensive end-to-end integration tests.
- Optimize slot-status generation using slot-indexed arrays.
- Introduce a color index using a "HashMap" for faster searches at larger scales.
- Add parking reservations and real-time sensor integration.
- Integrate a secure payment gateway.
- Add performance benchmarks and improve scalability.

Learning Outcomes

Through this project, we explored:

- Practical applications of data structures and algorithms.
- Efficient parking-slot allocation using "TreeSet".
- Fast vehicle lookup using "HashMap".
- Communication between Java and Python using TCP sockets.
- Persistent storage with SQLite.
- Web application development using Streamlit.
- Password-related security helpers and automated testing.
- The importance of consistency, security, and integration testing in multi-component systems.

Conclusion

GoParking demonstrates how data structures and algorithms can solve practical parking management problems. By combining a Python-based web interface, a Java parking engine, and SQLite persistence, the project provides a foundation for managing parking slots, vehicles, visit history, and parking fees.

The project also highlights important software engineering lessons, including selecting suitable data structures, integrating multiple technologies, maintaining consistent state, and testing complete application workflows.

Authors

Tesh Kumar Sahu
Soumya Ranjan Dash

Rungta College of Engineering & Technology, Bhilai

---

GoParking — Making Parking Management Smarter Through Data Structures and Algorithms.
