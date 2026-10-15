import java.util.Scanner;

public class Main {

    public static void main(String[] args) {

        Scanner scanner = new Scanner(System.in);

        // GoParking mein total 10 slots
        ParkingLot parkingLot = new ParkingLot(10);

        int choice;

        do {

            System.out.println("\n================================");
            System.out.println("        GoParking System");
            System.out.println("   Parking Allotment Management");
            System.out.println("================================");

            System.out.println("1. Park Vehicle");
            System.out.println("2. Remove Vehicle");
            System.out.println("3. Find Vehicle");
            System.out.println("4. Find Vehicles by Color");
            System.out.println("5. Display Parking Status");
            System.out.println("6. Exit");

            System.out.print("\nEnter your choice: ");

            choice = scanner.nextInt();
            scanner.nextLine();

            switch (choice) {

                case 1:

                    System.out.println("\n--- Park Vehicle ---");

                    System.out.print("Enter Registration Number: ");
                    String registrationNumber = scanner.nextLine();

                    System.out.print("Enter Vehicle Color: ");
                    String color = scanner.nextLine();

                    System.out.print("Enter Vehicle Type (Car/Bike): ");
                    String vehicleType = scanner.nextLine();

                    Vehicle vehicle = new Vehicle(
                            registrationNumber,
                            color,
                            vehicleType
                    );

                    parkingLot.parkVehicle(vehicle);

                    break;


                case 2:

                    System.out.println("\n--- Remove Vehicle ---");

                    System.out.print("Enter Registration Number: ");
                    String removeRegistrationNumber =
                            scanner.nextLine();

                    parkingLot.removeVehicle(
                            removeRegistrationNumber
                    );

                    break;


                case 3:

                    System.out.println("\n--- Find Vehicle ---");

                    System.out.print("Enter Registration Number: ");
                    String searchRegistrationNumber =
                            scanner.nextLine();

                    parkingLot.findVehicle(
                            searchRegistrationNumber
                    );

                    break;


                case 4:

                    System.out.println("\n--- Find Vehicles by Color ---");

                    System.out.print("Enter Color: ");
                    String searchColor = scanner.nextLine();

                    parkingLot.findVehiclesByColor(searchColor);

                    break;


                case 5:

                    parkingLot.displayParkingStatus();

                    break;


                case 6:

                    System.out.println(
                            "\nThank you for using GoParking!"
                    );

                    break;


                default:

                    System.out.println(
                            "Invalid choice. Please try again."
                    );
            }

        } while (choice != 6);

        scanner.close();
    }
}