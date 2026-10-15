public class ParkingLotSmokeTest {

    public static void main(String[] args) {
        ParkingLot lot = new ParkingLot(2);
        require(lot.getStatus().equals("STATUS|2|0|2"),
            "A new parking lot should start with every slot available.");
        require(lot.getAllParkingSlots().equals(
                "SLOTS|1|false||||2|false|||"),
            "A new parking lot should report every slot as empty: "
                + lot.getAllParkingSlots());

        String first = lot.parkVehicle(
            new Vehicle("ab-123", "Blue", "Sedan"));
        require(first.equals("OK|Vehicle parked|AB-123|Blue|Sedan|1"),
            "The first vehicle should receive the lowest slot.");
        require(lot.getAllParkingSlots().contains("|1|true|ab-123|"),
            "Parking a vehicle should mark its assigned slot occupied.");

        String duplicate = lot.parkVehicle(
            new Vehicle("AB-123", "Red", "Car"));
        require(duplicate.equals("ERROR|Vehicle already parked"),
            "The same vehicle must not occupy two slots.");
        require(lot.getOccupiedSlots() == 1,
            "Rejecting a duplicate must not change occupancy.");

        String second = lot.parkVehicle(
            new Vehicle("cd-456", "Green", "Motorcycle"));
        require(second.endsWith("|2"),
            "The second vehicle should receive the next slot.");

        String full = lot.parkVehicle(
            new Vehicle("ef-789", "Red", "Bicycle"));
        require(full.equals("ERROR|Parking lot is full"),
            "A full lot should reject additional vehicles.");

        String invalid = lot.parkVehicle(
            new Vehicle("ef-789", "Red", "Unlisted vehicle"));
        require(invalid.equals("ERROR|Invalid vehicle details"),
            "Unsupported vehicle categories should be rejected.");

        String removed = lot.removeVehicle("ab-123");
        require(removed.equals("OK|Vehicle removed|AB-123|1"),
            "Removing a vehicle should report its released slot.");
        require(lot.getAllParkingSlots().contains("|1|false||||"),
            "Removing a vehicle should make its slot available.");

        String third = lot.parkVehicle(
            new Vehicle("ef-789", "Red", "Bicycle"));
        require(third.endsWith("|1"),
            "The lowest released slot should be allocated next.");

        String found = lot.findVehicle("EF-789");
        require(found.equals("FOUND|EF-789|Red|Bicycle|1"),
            "Registration lookup should be case-insensitive.");

        ParkingLot restartedLot = new ParkingLot(2);
        require(restartedLot.getStatus().equals("STATUS|2|0|2"),
            "A fresh in-memory lot should start empty after a restart.");
        require(restartedLot.getAllParkingSlots().equals(
                "SLOTS|1|false||||2|false|||"),
            "A fresh in-memory lot should report all slots available.");

        require(restartedLot.restoreVehicle(
                "restore-1", "Black", "Sedan", 1),
            "An explicitly active persistent record should restore.");
        require(restartedLot.getAllParkingSlots().contains(
                "|1|true|RESTORE-1|"),
            "Restoring an active record should occupy its saved slot.");
        require(!restartedLot.restoreVehicle(
                "restore-2", "White", "Car", 1),
            "A restored occupied slot must not be assigned twice.");
        require(!restartedLot.restoreVehicle(
                "restore-1", "Black", "Sedan", 2),
            "A restored vehicle must not be assigned to a second slot.");

        System.out.println("ParkingLot smoke tests passed.");
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
