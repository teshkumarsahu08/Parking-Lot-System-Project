public class Vehicle {

    private String registrationNumber;
    private String color;
    private String vehicleType;

    public Vehicle(String registrationNumber, String color, String vehicleType) {
        this.registrationNumber = registrationNumber;
        this.color = color;
        this.vehicleType = vehicleType;
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

    @Override
    public String toString() {
        return "Registration Number: " + registrationNumber
                + ", Color: " + color
                + ", Vehicle Type: " + vehicleType;
    }
}