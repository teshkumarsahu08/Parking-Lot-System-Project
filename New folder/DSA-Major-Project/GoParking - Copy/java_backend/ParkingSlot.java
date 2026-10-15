public class ParkingSlot {

    private int slotNumber;
    private boolean occupied;
    private Vehicle vehicle;

    public ParkingSlot(int slotNumber) {
        this.slotNumber = slotNumber;
        this.occupied = false;
        this.vehicle = null;
    }

    public int getSlotNumber() {
        return slotNumber;
    }

    public boolean isOccupied() {
        return occupied;
    }

    public Vehicle getVehicle() {
        return vehicle;
    }

    public void parkVehicle(Vehicle vehicle) {
        this.vehicle = vehicle;
        this.occupied = true;
    }

    public Vehicle removeVehicle() {
        Vehicle removedVehicle = this.vehicle;
        this.vehicle = null;
        this.occupied = false;
        return removedVehicle;
    }

    @Override
    public String toString() {

        if (occupied) {
            return "Slot " + slotNumber + " - Occupied - " + vehicle;
        }

        return "Slot " + slotNumber + " - Available";
    }
}