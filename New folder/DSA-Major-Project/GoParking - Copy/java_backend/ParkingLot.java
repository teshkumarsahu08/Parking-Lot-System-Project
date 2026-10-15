
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.TreeSet;

public class ParkingLot {

    private static final Set<String> SUPPORTED_VEHICLE_TYPES =
        new HashSet<>(Arrays.asList(
            "motorcycle", "scooter", "bicycle", "hatchback car",
            "sedan", "suv", "electric car", "van", "pickup truck",
            "bus", "truck", "car", "bike", "other"
        ));

    private final int totalSlots;
    private final TreeSet<Integer> availableSlots;
    private final HashMap<String, ParkingSlot> vehicleMap;
    private final ArrayList<Vehicle> vehicles;
    private final ArrayList<ParkingHistory> parkingHistory;

    public ParkingLot(int totalSlots) {
        this.totalSlots = totalSlots;
        availableSlots = new TreeSet<>();
        vehicleMap = new HashMap<>();
        vehicles = new ArrayList<>();
        parkingHistory = new ArrayList<>();

        for (int i = 1; i <= totalSlots; i++) {
            availableSlots.add(i);
        }
    }

    // Normal parking
    public synchronized String parkVehicle(Vehicle vehicle) {
        if (vehicle == null ||
            vehicle.getRegistrationNumber() == null ||
            vehicle.getRegistrationNumber().trim().isEmpty() ||
            vehicle.getColor() == null ||
            vehicle.getColor().trim().isEmpty() ||
            vehicle.getVehicleType() == null ||
            !SUPPORTED_VEHICLE_TYPES.contains(
                vehicle.getVehicleType().trim().toLowerCase(Locale.ROOT))) {
            return "ERROR|Invalid vehicle details";
        }

        String reg = vehicle.getRegistrationNumber()
                            .trim().toUpperCase();

        if (vehicleMap.containsKey(reg)) {
            return "ERROR|Vehicle already parked";
        }

        if (availableSlots.isEmpty()) {
            return "ERROR|Parking lot is full";
        }

        int slotNumber = availableSlots.first();
        availableSlots.remove(slotNumber);

        ParkingSlot slot = new ParkingSlot(slotNumber);
        slot.parkVehicle(vehicle);

        vehicleMap.put(reg, slot);
        vehicles.add(vehicle);

        parkingHistory.add(new ParkingHistory(
            reg,
            vehicle.getColor(),
            vehicle.getVehicleType(),
            slotNumber
        ));

        return "OK|Vehicle parked|" + reg + "|"
            + vehicle.getColor() + "|"
            + vehicle.getVehicleType() + "|" + slotNumber;
    }

    // Restore a vehicle to its original slot after restart
    public synchronized boolean restoreVehicle(
            String registrationNumber,
            String color,
            String vehicleType,
            int slotNumber) {

        if (registrationNumber == null ||
            registrationNumber.trim().isEmpty() ||
            color == null ||
            vehicleType == null ||
            slotNumber < 1 ||
            slotNumber > totalSlots ||
            vehicleMap.containsKey(registrationNumber.trim().toUpperCase()) ||
            !availableSlots.contains(slotNumber)) {
            return false;
        }

        String reg = registrationNumber.trim().toUpperCase();
        Vehicle vehicle = new Vehicle(reg, color, vehicleType);
        ParkingSlot slot = new ParkingSlot(slotNumber);
        slot.parkVehicle(vehicle);

        availableSlots.remove(slotNumber);
        vehicleMap.put(reg, slot);
        vehicles.add(vehicle);

        return true;
    }

    public synchronized String removeVehicle(String registrationNumber) {
        if (registrationNumber == null) {
            return "ERROR|Invalid registration number";
        }

        String reg = registrationNumber.trim().toUpperCase();
        ParkingSlot slot = vehicleMap.get(reg);

        if (slot == null) {
            return "ERROR|Vehicle not found";
        }

        Vehicle vehicle = slot.getVehicle();

        for (int i = parkingHistory.size() - 1; i >= 0; i--) {
            ParkingHistory history = parkingHistory.get(i);

            if (history.getRegistrationNumber().equalsIgnoreCase(reg)
                    && history.getExitTime() == null) {
                history.recordExit();
                break;
            }
        }

        slot.removeVehicle();
        vehicleMap.remove(reg);
        vehicles.remove(vehicle);
        availableSlots.add(slot.getSlotNumber());

        return "OK|Vehicle removed|" + reg + "|"
            + slot.getSlotNumber();
    }

    public synchronized String findVehicle(String registrationNumber) {
        if (registrationNumber == null) {
            return "ERROR|Invalid registration number";
        }

        String reg = registrationNumber.trim().toUpperCase();
        ParkingSlot slot = vehicleMap.get(reg);

        if (slot == null || slot.getVehicle() == null) {
            return "ERROR|Vehicle not found";
        }

        Vehicle v = slot.getVehicle();

        return "FOUND|" + reg + "|"
            + v.getColor() + "|"
            + v.getVehicleType() + "|"
            + slot.getSlotNumber();
    }

    public synchronized String findVehiclesByColor(String color) {
        StringBuilder result = new StringBuilder("COLOR");

        for (Vehicle v : vehicles) {
            if (v.getColor().equalsIgnoreCase(color.trim())) {
                ParkingSlot slot =
                    vehicleMap.get(v.getRegistrationNumber().toUpperCase());

                result.append("|")
                    .append(v.getRegistrationNumber()).append("|")
                    .append(v.getColor()).append("|")
                    .append(v.getVehicleType()).append("|")
                    .append(slot.getSlotNumber());
            }
        }

        return result.toString();
    }

    public synchronized String getStatus() {
        return "STATUS|" + totalSlots + "|"
            + vehicleMap.size() + "|"
            + availableSlots.size();
    }

    public synchronized String getAllParkingSlots() {
        StringBuilder result = new StringBuilder("SLOTS");

        for (int i = 1; i <= totalSlots; i++) {
            result.append("|").append(i);

            boolean occupied = false;
            Vehicle vehicle = null;

            for (ParkingSlot slot : vehicleMap.values()) {
                if (slot.getSlotNumber() == i) {
                    occupied = true;
                    vehicle = slot.getVehicle();
                    break;
                }
            }

            result.append("|").append(occupied);

            if (occupied && vehicle != null) {
                result.append("|").append(vehicle.getRegistrationNumber())
                    .append("|").append(vehicle.getColor())
                    .append("|").append(vehicle.getVehicleType());
            } else {
                result.append("|||");
            }
        }

        return result.toString();
    }

    public synchronized ArrayList<ParkingHistory> getParkingHistory() {
        return new ArrayList<>(parkingHistory);
    }

    public synchronized void displayParkingHistory() {
        for (ParkingHistory history : parkingHistory) {
            System.out.println(history);
        }
    }

    public synchronized void displayParkingStatus() {
        System.out.println(getStatus());
        System.out.println(getAllParkingSlots());
    }

    public synchronized int getNextAvailableSlot() {
        return availableSlots.isEmpty() ? -1 : availableSlots.first();
    }

    public synchronized int getTotalSlots() {
        return totalSlots;
    }

    public synchronized int getOccupiedSlots() {
        return vehicleMap.size();
    }

    public synchronized int getAvailableSlots() {
        return availableSlots.size();
    }

    public synchronized int getVehicleSlot(String registrationNumber) {
        if (registrationNumber == null) {
            return -1;
        }

        ParkingSlot slot =
            vehicleMap.get(registrationNumber.trim().toUpperCase());

        return slot == null ? -1 : slot.getSlotNumber();
    }
}