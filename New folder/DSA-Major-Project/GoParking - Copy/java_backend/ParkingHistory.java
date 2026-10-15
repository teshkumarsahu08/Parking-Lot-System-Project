
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;

public class ParkingHistory {

    private String registrationNumber;
    private String color;
    private String vehicleType;
    private int slotNumber;
    private LocalDateTime entryTime;
    private LocalDateTime exitTime;

    public ParkingHistory(
            String registrationNumber,
            String color,
            String vehicleType,
            int slotNumber
    ) {
        this.registrationNumber = registrationNumber;
        this.color = color;
        this.vehicleType = vehicleType;
        this.slotNumber = slotNumber;
        this.entryTime = LocalDateTime.now();
        this.exitTime = null;
    }

    public void recordExit() {
        this.exitTime = LocalDateTime.now();
    }

    public String getRegistrationNumber() {
        return registrationNumber;
    }

    public String getColor() {
        return color;
    }

    public String getVehicleType() {
        return vehicleType;
    }

    public int getSlotNumber() {
        return slotNumber;
    }

    public LocalDateTime getEntryTime() {
        return entryTime;
    }

    public LocalDateTime getExitTime() {
        return exitTime;
    }

    public String getFormattedEntryTime() {
        return entryTime.format(
            DateTimeFormatter.ofPattern("dd-MM-yyyy HH:mm:ss")
        );
    }

    public String getFormattedExitTime() {
        if (exitTime == null) {
            return "Still Parked";
        }

        return exitTime.format(
            DateTimeFormatter.ofPattern("dd-MM-yyyy HH:mm:ss")
        );
    }

    @Override
    public String toString() {
        return "Vehicle: " + registrationNumber
                + " | Color: " + color
                + " | Type: " + vehicleType
                + " | Slot: " + slotNumber
                + " | Entry: " + getFormattedEntryTime()
                + " | Exit: " + getFormattedExitTime();
    }
}